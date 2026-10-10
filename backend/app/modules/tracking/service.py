from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.errors import NotFound
from app.core.units import qty
from app.modules.analytics import service as analytics
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance.models import Invoice, Payment
from app.modules.masters.models import Buyer, FabricType
from app.modules.orders.models import Order, OrderStatus, new_tracking_token
from app.modules.production import service as production
from app.modules.production.models import ProductionLog, WorkOrder, WorkOrderStatus
from app.modules.quality.models import Roll, RollStatus
from app.modules.tracking.schemas import BuyerStage, Risk

IST = timezone(timedelta(hours=5, minutes=30))
ZERO = Decimal(0)
# roll status -> buyer bucket; in_process rolls are woven but not yet at the QC table
BUCKET = {
    RollStatus.in_process: "in_qc",
    RollStatus.awaiting_qc: "in_qc",
    RollStatus.rework: "in_qc",
    RollStatus.passed: "passed",
    RollStatus.rejected: "rejected",
    RollStatus.dispatched: "shipped",
}
STARTED = {WorkOrderStatus.queued, WorkOrderStatus.running, WorkOrderStatus.paused}


def order_by_token(db: Session, token: str) -> Order:
    order = db.scalar(select(Order).where(Order.tracking_token == token))
    if not order:
        raise NotFound("Tracking link is not valid")
    return order


# --- pure: the buyer stage is a function of facts, never a stored column


# stages = route work orders in seq order, each {stage, status, planned, produced}
def derive_stage(
    order_status: OrderStatus, qty_m: Decimal, stages: list[dict], m: dict[str, Decimal]
) -> tuple[BuyerStage, str | None, int | None]:
    if order_status == OrderStatus.cancelled:
        return BuyerStage.cancelled, None, None
    if order_status == OrderStatus.draft:
        return BuyerStage.order_received, None, None
    if order_status == OrderStatus.closed or m["shipped"] >= qty_m:
        return BuyerStage.shipped, None, None
    if m["shipped"] > 0:
        return BuyerStage.partly_shipped, None, None
    if m["passed"] >= qty_m:
        return BuyerStage.ready_to_ship, None, None
    all_done = bool(stages) and all(s["status"] == WorkOrderStatus.done for s in stages)
    if all_done and m["in_qc"] > 0:
        return BuyerStage.being_checked, None, None
    if all_done and m["passed"] > 0:
        return BuyerStage.ready_to_ship, None, None
    if any(s["status"] in STARTED or s["status"] == WorkOrderStatus.done for s in stages):
        current = next((s for s in stages if s["status"] != WorkOrderStatus.done), stages[-1])
        pct = int(min(current["produced"] / current["planned"], 1) * 100)
        return BuyerStage.in_production, str(current["stage"]), pct
    return BuyerStage.waiting_for_yarn, None, None


# --- facts gathered from other modules (read only)


def _stage_progress(db: Session, order_id: int) -> list[dict]:
    work_orders = db.scalars(
        select(WorkOrder)
        .where(WorkOrder.order_id == order_id, WorkOrder.roll_id.is_(None))
        .order_by(WorkOrder.seq)
    ).all()
    try:
        progress = production.order_progress(db, order_id)
    except NotImplementedError:
        # until production ships order_progress: sum the logs per work order ourselves
        produced = dict(
            db.execute(
                select(ProductionLog.work_order_id, func.sum(ProductionLog.qty))
                .where(ProductionLog.work_order_id.in_([w.id for w in work_orders] or [0]))
                .group_by(ProductionLog.work_order_id)
            ).all()
        )
        progress = {w.stage: {"produced": produced.get(w.id, ZERO)} for w in work_orders}
    return [
        {
            "stage": w.stage,
            "status": w.status,
            "planned": w.planned_qty,
            "produced": Decimal(progress.get(w.stage, {}).get("produced", ZERO)),
        }
        for w in work_orders
    ]


def _metres(db: Session, order_id: int) -> dict[str, Decimal]:
    rows = db.execute(
        select(Roll.status, func.sum(Roll.length_m))
        .where(Roll.order_id == order_id)
        .group_by(Roll.status)
    ).all()
    m = {"produced": ZERO, "in_qc": ZERO, "passed": ZERO, "rejected": ZERO, "shipped": ZERO}
    for status, metres in rows:
        m[BUCKET[status]] += metres
        m["produced"] += metres
    return {k: qty(v) for k, v in m.items()}


def _estimate(db: Session, order: Order, stage: BuyerStage) -> tuple:
    try:
        est = analytics.delivery_estimate(db, order.id)
        return est.get("projected_finish"), est.get("risk")
    except NotImplementedError:
        # estimate pending; a missed deadline is still a plain fact
        done = stage in (BuyerStage.shipped, BuyerStage.cancelled)
        late = not done and datetime.now(IST).date() > order.deadline
        return None, Risk.late if late else None


def _timeline(db: Session, order: Order, internal: bool) -> list[dict]:
    events = [{"at": order.created_at, "title": "Order received"}]
    if order.confirmed_at:
        events.append({"at": order.confirmed_at, "title": "Order confirmed"})
    for w in db.scalars(
        select(WorkOrder).where(WorkOrder.order_id == order.id, WorkOrder.roll_id.is_(None))
    ):
        if w.started_at:
            events.append({"at": w.started_at, "title": f"{w.stage.capitalize()} started"})
        if w.finished_at:
            events.append({"at": w.finished_at, "title": f"{w.stage.capitalize()} finished"})
    first_roll, first_pass = db.execute(
        select(func.min(Roll.created_at), func.min(Roll.passed_at)).where(Roll.order_id == order.id)
    ).one()
    if first_roll:
        events.append({"at": first_roll, "title": "First roll woven"})
    if first_pass:
        events.append({"at": first_pass, "title": "First roll passed quality check"})
    for d, count, metres in _dispatch_rows(db, order.id):
        if d.status == DispatchStatus.confirmed:
            label = f"{d.code} on {d.vehicle_no}" if internal else "Dispatched"
            events.append({"at": d.confirmed_at, "title": f"{label}: {count} rolls, {metres} m"})
    return sorted(events, key=lambda e: e["at"])


def _dispatch_rows(db: Session, order_id: int) -> list:
    return db.execute(
        select(Dispatch, func.count(Roll.id), func.coalesce(func.sum(Roll.length_m), 0))
        .outerjoin(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .outerjoin(Roll, Roll.id == DispatchRoll.roll_id)
        .where(Dispatch.order_id == order_id)
        .group_by(Dispatch.id)
        .order_by(Dispatch.id)
    ).all()


def _card(db: Session, order: Order, internal: bool) -> dict:
    stages = _stage_progress(db, order.id)
    m = _metres(db, order.id)
    stage, production_stage, pct = derive_stage(order.status, order.qty_m, stages, m)
    projected, risk = _estimate(db, order, stage)
    fabric = db.get(FabricType, order.fabric_type_id)
    return {
        "order_code": order.code,
        "fabric": fabric.name,
        "colour": order.colour,
        "qty_m": order.qty_m,
        "deadline": order.deadline,
        "stage": stage,
        "production_stage": production_stage,
        "progress_pct": pct,
        "metres": m,
        "projected_finish": projected,
        "risk": risk,
        "timeline": _timeline(db, order, internal),
    }


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# buyer stage derived from work orders, rolls and dispatches + metres in each bucket
def order_stage(db: Session, order_id: int) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    return _card(db, order, internal=False)


# --- routes


def public_view(db: Session, token: str) -> dict:
    return _card(db, order_by_token(db, token), internal=False)


def order_view(db: Session, order_id: int) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    on_dispatch = dict(
        db.execute(
            select(DispatchRoll.roll_id, Dispatch.code)
            .join(Dispatch, Dispatch.id == DispatchRoll.dispatch_id)
            .where(Dispatch.order_id == order.id)
        ).all()
    )
    rolls = db.scalars(select(Roll).where(Roll.order_id == order.id).order_by(Roll.code)).all()
    paid = (
        select(Payment.invoice_id, func.sum(Payment.amount_paise).label("paid"))
        .group_by(Payment.invoice_id)
        .subquery()
    )
    invoices = db.execute(
        select(Invoice, func.coalesce(paid.c.paid, 0))
        .outerjoin(paid, paid.c.invoice_id == Invoice.id)
        .where(Invoice.order_id == order.id)
        .order_by(Invoice.id)
    ).all()
    return {
        **_card(db, order, internal=True),
        "order_id": order.id,
        "order_status": order.status,
        "buyer_name": db.get(Buyer, order.buyer_id).name,
        "tracking_token": order.tracking_token,
        "rolls": [
            {
                "id": r.id,
                "code": r.code,
                "length_m": r.length_m,
                "status": r.status,
                "shade_band": r.shade_band,
                "dispatch_code": on_dispatch.get(r.id),
            }
            for r in rolls
        ],
        "dispatches": [
            {
                "id": d.id,
                "code": d.code,
                "status": d.status,
                "vehicle_no": d.vehicle_no,
                "confirmed_at": d.confirmed_at,
                "roll_count": count,
                "metres": qty(metres),
            }
            for d, count, metres in _dispatch_rows(db, order.id)
        ],
        "invoices": [
            {
                "id": inv.id,
                "code": inv.code,
                "total_paise": inv.total_paise,
                "paid_paise": paid_paise,
                "status": inv.status,
                "due_date": inv.due_date,
            }
            for inv, paid_paise in invoices
        ],
    }


# revoke the old buyer link by issuing a new unguessable token
def rotate_token(db: Session, user: User, order_id: int) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise NotFound(f"Order {order_id} not found")
    order.tracking_token = new_tracking_token()
    audit.record(db, user.id, "rotate_tracking_token", "orders", order.id)
    db.commit()
    return order_view(db, order.id)
