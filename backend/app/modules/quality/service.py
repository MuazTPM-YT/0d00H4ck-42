from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.core import audit, events
from app.core.enums import Stage, Unit
from app.core.errors import Conflict, NotFound
from app.core.idempotency import run_once
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll
from app.modules.inventory.models import ItemKind, MoveReason, StockMove, YarnBatch
from app.modules.inventory.service import location_id
from app.modules.masters.models import (
    Buyer,
    FabricType,
    Location,
    LocationKind,
    Machine,
    Shift,
    Supplier,
    Worker,
    YarnItem,
)
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder
from app.modules.quality.models import (
    DefectType,
    QcCheck,
    QcDecision,
    Roll,
    RollBatch,
    RollEvent,
    RollStatus,
)
from app.modules.quality.schemas import QcCheckIn, QcCheckOut, RollOut

ROLL_TRANSITIONS = {
    RollStatus.in_process: {RollStatus.awaiting_qc},
    RollStatus.awaiting_qc: {RollStatus.passed, RollStatus.rework, RollStatus.rejected},
    RollStatus.rework: {RollStatus.awaiting_qc, RollStatus.rejected},
    RollStatus.passed: {RollStatus.dispatched},
}

DECISION_STATUS = {
    QcDecision.pass_: RollStatus.passed,
    QcDecision.rework: RollStatus.rework,
    QcDecision.reject: RollStatus.rejected,
}
# where the fabric goes after the decision; rework stays on the floor
DECISION_MOVE = {
    QcDecision.pass_: (LocationKind.finished, MoveReason.qc_pass),
    QcDecision.reject: (LocationKind.rejected, MoveReason.qc_reject),
}
# third look settles it: after this many checks a roll passes or is rejected
MAX_REWORK_CHECKS = 2
SUMMARY_KEY = {
    QcDecision.pass_: "passed",
    QcDecision.rework: "rework",
    QcDecision.reject: "rejected",
}


def list_rolls(
    db: Session,
    page: Page,
    status: RollStatus | None = None,
    order_id: int | None = None,
    code: str | None = None,
) -> dict:
    stmt = select(Roll).order_by(Roll.id.desc())
    if status:
        stmt = stmt.where(Roll.status == status)
    if order_id:
        stmt = stmt.where(Roll.order_id == order_id)
    if code:
        stmt = stmt.where(Roll.code == code)
    return paginate(db, stmt, page)


# --- 4-point system (pure). Older checks carry no points: a hole is 4, anything else 1.


def defect_points(defects: list[dict]) -> int:
    return sum(
        d["count"] * d.get("points", 4 if d["type"] == DefectType.hole else 1) for d in defects
    )


# points per 100 m² of cloth; the buyer's limit (often 40) decides, the inspector applies it
def points_per_100m2(points: int, length_m: Decimal, width_cm: Decimal | None) -> Decimal | None:
    if not width_cm or length_m <= 0:
        return None
    area = Decimal(length_m) * Decimal(width_cm) / 100
    return (Decimal(points) * 100 / area).quantize(Decimal("0.1"), ROUND_HALF_UP)


def _on_hand(db: Session, roll_id: int, location: int) -> Decimal:
    def total(col):
        return db.scalar(
            select(func.coalesce(func.sum(StockMove.qty), 0)).where(
                StockMove.roll_id == roll_id, col == location
            )
        )

    return Decimal(total(StockMove.to_location_id)) - Decimal(total(StockMove.from_location_id))


# R11: one inspection, one fact. Row lock so two inspectors cannot decide the same roll.
# A repeated scan key returns the first answer instead of a second check.
def decide(
    db: Session, roll_id: int, body: QcCheckIn, user_id: int, at: datetime | None = None
) -> dict:
    if body.idempotency_key:
        result = run_once(
            db,
            body.idempotency_key,
            "quality.decide",
            lambda: _decide(db, roll_id, body, user_id, at),
        )
    else:
        result = _decide(db, roll_id, body, user_id, at)
    db.commit()
    events.publish("quality", {"type": "qc", "id": roll_id})
    events.publish("orders", {"type": "roll", "id": roll_id})
    if body.decision in DECISION_MOVE:
        events.publish("stock", {"type": "roll", "id": roll_id})
    if result["rework_work_order_id"]:
        events.publish("machines", {"type": "work_order", "id": result["rework_work_order_id"]})
    return result


# rework only for an order still being made, and not round and round
def _can_rework(db: Session, roll: Roll, previous_checks: int) -> None:
    order = db.get(Order, roll.order_id)
    if order.status != OrderStatus.confirmed:
        raise Conflict(
            f"Order {order.code} is {order.status}: nothing to rework for, reject the roll instead",
            field="decision",
            code="order_not_open",
        )
    if previous_checks >= MAX_REWORK_CHECKS:
        raise Conflict(
            f"Third check: pass or reject. {roll.code} has been checked {previous_checks} times",
            field="decision",
            code="rework_limit",
        )


def _decide(db: Session, roll_id: int, body: QcCheckIn, user_id: int, at: datetime | None) -> dict:
    # production imports this module for ROLL_TRANSITIONS, so import it late
    from app.modules.production.service import create_rework_work_order

    roll = db.scalar(select(Roll).where(Roll.id == roll_id).with_for_update())
    if not roll:
        raise NotFound(f"Roll {roll_id} not found")
    if roll.status != RollStatus.awaiting_qc:
        raise Conflict(f"{roll.code} is {roll.status}, not waiting for QC", code="not_awaiting_qc")
    new = DECISION_STATUS[body.decision]
    check_transition(ROLL_TRANSITIONS, roll.status, new)
    when = at or datetime.now(UTC)
    attempt = db.scalar(select(func.count()).where(QcCheck.roll_id == roll.id)) + 1
    if body.decision == QcDecision.rework:
        _can_rework(db, roll, attempt - 1)
    passed = body.decision == QcDecision.pass_
    check = QcCheck(
        roll_id=roll.id,
        inspector_id=user_id,
        at=when,
        attempt_no=attempt,
        decision=body.decision,
        defects=[d.model_dump(mode="json") for d in body.defects],
        shade_band=body.shade_band if passed else None,
        gsm=body.gsm,
        width_cm=body.width_cm,
        notes=body.note,
    )
    db.add(check)
    data = {"from": roll.status, "to": new, "attempt": attempt}
    audit.record(db, user_id, str(new), "rolls", roll.id, body.note, data)
    rework_wo_id = None
    if body.decision in DECISION_MOVE:
        kind, reason = DECISION_MOVE[body.decision]
        # the roll must be where the ledger says it is, or the move would invent stock
        if _on_hand(db, roll.id, roll.location_id) < roll.length_m:
            raise Conflict(
                f"Stock ledger does not show {roll.code} at its location", code="stock_mismatch"
            )
        # look up before touching the roll: an autoflushing session would flush a half-set row
        to = location_id(db, kind)
        roll.status = new
        db.add(
            StockMove(
                at=when,
                item_kind=ItemKind.fabric,
                roll_id=roll.id,
                qty=roll.length_m,
                unit=Unit.m,
                from_location_id=roll.location_id,
                to_location_id=to,
                reason=reason,
                ref_type="roll",
                ref_id=roll.id,
                user_id=user_id,
            )
        )
        roll.location_id = to
        if passed:
            roll.shade_band, roll.passed_at = body.shade_band, when
    else:
        roll.status = new
        fabric = db.scalar(
            select(FabricType)
            .join(Order, Order.fabric_type_id == FabricType.id)
            .where(Order.id == roll.order_id)
        )
        stage = body.rework_stage or fabric.stages[-1].stage
        rework_wo_id = create_rework_work_order(db, roll.id, stage, user_id).id
    db.add(
        RollEvent(
            roll_id=roll.id,
            at=when,
            kind=f"qc_{body.decision}",
            work_order_id=rework_wo_id,
            note=body.note,
        )
    )
    db.flush()
    return {
        "check": QcCheckOut.model_validate(check),
        "roll": RollOut.model_validate(roll),
        "rework_work_order_id": rework_wo_id,
    }


# roll + the names around it in one query; waiting since = last thing that happened to it
def _roll_rows() -> Select:
    last_event = (
        select(RollEvent.roll_id, func.max(RollEvent.at).label("at"))
        .group_by(RollEvent.roll_id)
        .subquery()
    )
    loom = aliased(Machine)
    return (
        select(
            Roll.id,
            Roll.code,
            Roll.status,
            Roll.length_m,
            Roll.shade_band,
            Roll.order_id,
            Order.code.label("order_code"),
            Order.status.label("order_status"),
            Buyer.name.label("buyer_name"),
            FabricType.name.label("fabric_name"),
            FabricType.gsm.label("fabric_gsm"),
            FabricType.width_cm.label("fabric_width_cm"),
            Order.colour,
            loom.code.label("loom_code"),
            Shift.name.label("shift_name"),
            Worker.name.label("weaver_name"),
            Roll.created_at,
            func.coalesce(last_event.c.at, Roll.created_at).label("waiting_since"),
        )
        .join(Order, Order.id == Roll.order_id)
        .join(Buyer, Buyer.id == Order.buyer_id)
        .join(FabricType, FabricType.id == Order.fabric_type_id)
        .join(loom, loom.id == Roll.loom_machine_id)
        .join(Shift, Shift.id == Roll.shift_id)
        .outerjoin(Worker, Worker.id == Roll.weaver_id)
        .outerjoin(last_event, last_event.c.roll_id == Roll.id)
    )


def _waiting_count(db: Session) -> int:
    return db.scalar(select(func.count()).where(Roll.status == RollStatus.awaiting_qc))


# R12: rolls waiting for QC, longest wait first
def queue(db: Session, page: Page) -> dict:
    stmt = (
        _roll_rows()
        .where(Roll.status == RollStatus.awaiting_qc)
        .order_by("waiting_since", Roll.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return {"items": db.execute(stmt).mappings().all(), "total": _waiting_count(db)}


def roll_detail(db: Session, roll_id: int) -> dict:
    row = db.execute(_roll_rows().where(Roll.id == roll_id)).mappings().first()
    if not row:
        raise NotFound(f"Roll {roll_id} not found")
    checks = db.scalars(
        select(QcCheck).where(QcCheck.roll_id == roll_id).order_by(QcCheck.attempt_no)
    ).all()
    return {**row, "checks": checks}


Loom = aliased(Machine)


def _checks_stmt() -> Select:
    return (
        select(QcCheck, Roll.code, Roll.order_id, Order.code, Loom.code, Roll.length_m, User.name)
        .join(Roll, Roll.id == QcCheck.roll_id)
        .join(Order, Order.id == Roll.order_id)
        .join(Loom, Loom.id == Roll.loom_machine_id)
        .join(User, User.id == QcCheck.inspector_id)
    )


def _width_of(db: Session, check: QcCheck, order_id: int, widths: dict[int, Decimal]) -> Decimal:
    if check.width_cm:
        return check.width_cm
    if order_id not in widths:
        widths[order_id] = db.scalar(
            select(FabricType.width_cm)
            .join(Order, Order.fabric_type_id == FabricType.id)
            .where(Order.id == order_id)
        )
    return widths[order_id]


def _check_rows(db: Session, rows) -> list[dict]:
    widths: dict[int, Decimal] = {}
    out = []
    for c, roll_code, order_id, order_code, loom_code, length_m, inspector in rows:
        points = defect_points(c.defects)
        defects = [
            {**d, "points": d.get("points", 4 if d["type"] == DefectType.hole else 1)}
            for d in c.defects
        ]
        out.append(
            {
                "id": c.id,
                "roll_id": c.roll_id,
                "roll_code": roll_code,
                "order_id": order_id,
                "order_code": order_code,
                "loom_code": loom_code,
                "length_m": length_m,
                "at": c.at,
                "attempt_no": c.attempt_no,
                "decision": c.decision,
                "defects": defects,
                "shade_band": c.shade_band,
                "gsm": c.gsm,
                "width_cm": c.width_cm,
                "notes": c.notes,
                "inspector_name": inspector,
                "points": points,
                "score": points_per_100m2(points, length_m, _width_of(db, c, order_id, widths)),
            }
        )
    return out


def list_checks(
    db: Session,
    page: Page,
    decision: QcDecision | None = None,
    order_id: int | None = None,
    machine_id: int | None = None,
    roll_id: int | None = None,
) -> dict:
    stmt = _checks_stmt()
    if decision:
        stmt = stmt.where(QcCheck.decision == decision)
    if order_id:
        stmt = stmt.where(Roll.order_id == order_id)
    if machine_id:
        stmt = stmt.where(Roll.loom_machine_id == machine_id)
    if roll_id:
        stmt = stmt.where(QcCheck.roll_id == roll_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(QcCheck.at.desc(), QcCheck.id.desc()).limit(page.limit).offset(page.offset)
    ).all()
    return {"items": _check_rows(db, rows), "total": total}


def _top(groups: dict[str, dict[str, int]], n: int = 10) -> list[dict]:
    rows = [{"key": k, **v} for k, v in groups.items() if v["defects"]]
    return sorted(rows, key=lambda r: (-r["defects"], r["key"]))[:n]


# R12 + R13: pass/fail over the window, and which looms and orders the defects come from
def summary(db: Session, days: int) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(QcCheck.attempt_no, QcCheck.decision, QcCheck.defects, Machine.code, Order.code)
        .join(Roll, Roll.id == QcCheck.roll_id)
        .join(Machine, Machine.id == Roll.loom_machine_id)
        .join(Order, Order.id == Roll.order_id)
        .where(QcCheck.at >= since)
    ).all()
    first = {"passed": 0, "rework": 0, "rejected": 0}
    every = dict(first)
    by_type: dict[str, int] = defaultdict(int)
    by_machine: dict[str, dict[str, int]] = defaultdict(lambda: {"checks": 0, "defects": 0})
    by_order: dict[str, dict[str, int]] = defaultdict(lambda: {"checks": 0, "defects": 0})
    for attempt, decision, defects, machine, order in rows:
        key = SUMMARY_KEY[decision]
        every[key] += 1
        if attempt == 1:
            first[key] += 1
        count = 0
        for d in defects or []:
            by_type[d["type"]] += d["count"]
            count += d["count"]
        for groups, k in ((by_machine, machine), (by_order, order)):
            groups[k]["checks"] += 1
            groups[k]["defects"] += count
    firsts = sum(first.values())
    return {
        "days": days,
        "waiting": _waiting_count(db),
        "first_attempt": first,
        "all_attempts": every,
        "pass_rate_pct": round(100 * first["passed"] / firsts, 1) if firsts else None,
        "defects_by_type": dict(by_type),
        "by_machine": _top(by_machine),
        "by_order": _top(by_order),
    }


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# full genealogy: order, loom, shift, weaver, yarn batches + suppliers, qc attempts, events
def roll_trace(db: Session, roll_id: int) -> dict:
    roll = db.get(Roll, roll_id)
    if not roll:
        raise NotFound(f"Roll {roll_id} not found")
    order = db.get(Order, roll.order_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    loom = db.get(Machine, roll.loom_machine_id)
    shift = db.get(Shift, roll.shift_id)
    weaver = db.get(Worker, roll.weaver_id) if roll.weaver_id else None
    location = db.get(Location, roll.location_id)
    yarn = db.execute(
        select(RollBatch.kg, YarnBatch, YarnItem, Supplier)
        .join(YarnBatch, YarnBatch.id == RollBatch.yarn_batch_id)
        .join(Supplier, Supplier.id == YarnBatch.supplier_id)
        .outerjoin(YarnItem, YarnItem.id == YarnBatch.yarn_item_id)
        .where(RollBatch.roll_id == roll.id)
        .order_by(RollBatch.kg.desc())
    ).all()
    Job = aliased(Machine)
    events_rows = db.execute(
        select(RollEvent, Job.code, WorkOrder.code)
        .outerjoin(Job, Job.id == RollEvent.machine_id)
        .outerjoin(WorkOrder, WorkOrder.id == RollEvent.work_order_id)
        .where(RollEvent.roll_id == roll.id)
        .order_by(RollEvent.at, RollEvent.id)
    ).all()
    jobs = db.execute(
        select(WorkOrder, Job.code)
        .outerjoin(Job, Job.id == WorkOrder.machine_id)
        .where(WorkOrder.roll_id == roll.id)
        .order_by(WorkOrder.id)
    ).all()
    dispatch = db.scalar(
        select(Dispatch)
        .join(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .where(DispatchRoll.roll_id == roll.id)
    )
    checks = db.execute(
        _checks_stmt().where(QcCheck.roll_id == roll.id).order_by(QcCheck.attempt_no)
    ).all()
    return {
        "roll": {
            **{c: getattr(roll, c) for c in ("id", "code", "status", "length_m", "shade_band")},
            **{c: getattr(roll, c) for c in ("dye_lot", "passed_at", "created_at")},
            "location_code": location.code,
            "location_name": location.name,
        },
        "order": {
            **{c: getattr(order, c) for c in ("id", "code", "status", "colour", "qty_m")},
            "deadline": order.deadline,
            "buyer_name": db.get(Buyer, order.buyer_id).name,
        },
        "fabric": {
            **{c: getattr(fabric, c) for c in ("code", "name", "width_cm", "gsm")},
            "route": [s.stage for s in fabric.stages],
        },
        "loom": {"id": loom.id, "code": loom.code, "name": loom.name},
        "shift": {"id": shift.id, "code": shift.code, "name": shift.name},
        "weaver": {"id": weaver.id, "code": weaver.code, "name": weaver.name} if weaver else None,
        "yarn": [
            {
                "batch_id": b.id,
                "batch_code": b.code,
                "kg": kg,
                "yarn": f"{item.fibre} {item.count} {item.colour}" if item else "Unidentified",
                "supplier_code": s.code,
                "supplier_name": s.name,
                "supplier_lot": b.supplier_lot,
            }
            for kg, b, item, s in yarn
        ],
        "checks": _check_rows(db, checks),
        "events": [
            {
                "at": e.at,
                "kind": e.kind,
                "machine_code": machine,
                "work_order_code": wo,
                "note": e.note,
            }
            for e, machine, wo in events_rows
        ],
        "rework_jobs": [
            {
                "id": wo.id,
                "code": wo.code,
                "stage": wo.stage,
                "status": wo.status,
                "machine_code": machine,
            }
            for wo, machine in jobs
        ],
        "dispatch": {"id": dispatch.id, "code": dispatch.code, "status": dispatch.status}
        if dispatch
        else None,
        "rework_stages": [s.stage for s in fabric.stages if s.stage != Stage.spinning],
    }
