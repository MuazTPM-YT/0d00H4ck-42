from collections import Counter, defaultdict
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
from app.core.units import qty
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll
from app.modules.inventory.models import ItemKind, MoveReason, StockMove, YarnBatch
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
from app.modules.orders.models import Order
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
from app.modules.quality.schemas import InspectIn

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
ZERO = Decimal(0)


def _now() -> datetime:
    return datetime.now(UTC)


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


def _pct(part: int, whole: int) -> Decimal | None:
    if not whole:
        return None
    return (Decimal(part) * 100 / whole).quantize(Decimal("0.1"), ROUND_HALF_UP)


# --- reads


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


# rolls on the QC table, the one waiting longest first
def queue(db: Session, page: Page) -> dict:
    ready = (
        select(RollEvent.roll_id, func.max(RollEvent.at).label("ready_at"))
        .group_by(RollEvent.roll_id)
        .subquery()
    )
    tries = select(QcCheck.roll_id, func.count().label("n")).group_by(QcCheck.roll_id).subquery()
    ready_at = func.coalesce(ready.c.ready_at, Roll.created_at)
    stmt = (
        select(
            Roll,
            Order,
            Buyer.name,
            FabricType.name,
            Loom.code,
            Shift.code,
            Worker.name,
            ready_at,
            func.coalesce(tries.c.n, 0),
        )
        .join(Order, Order.id == Roll.order_id)
        .join(Buyer, Buyer.id == Order.buyer_id)
        .join(FabricType, FabricType.id == Order.fabric_type_id)
        .join(Loom, Loom.id == Roll.loom_machine_id)
        .join(Shift, Shift.id == Roll.shift_id)
        .outerjoin(Worker, Worker.id == Roll.weaver_id)
        .outerjoin(ready, ready.c.roll_id == Roll.id)
        .outerjoin(tries, tries.c.roll_id == Roll.id)
        .where(Roll.status == RollStatus.awaiting_qc)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(ready_at, Roll.id).limit(page.limit).offset(page.offset)).all()
    items = [
        {
            "id": r.id,
            "code": r.code,
            "order_id": o.id,
            "order_code": o.code,
            "buyer_name": buyer,
            "fabric_name": fabric,
            "colour": o.colour,
            "loom_code": loom,
            "shift_code": shift,
            "weaver_name": weaver,
            "length_m": r.length_m,
            "ready_at": at,
            "attempt_no": n + 1,
            "deadline": o.deadline,
        }
        for r, o, buyer, fabric, loom, shift, weaver, at, n in rows
    ]
    return {"items": items, "total": total}


# what passed, what failed and what waits; defects by type, loom and order (R12, R13)
def summary(db: Session, days: int, now: datetime | None = None) -> dict:
    since = (now or _now()) - timedelta(days=days)
    rows = db.execute(
        select(
            QcCheck.roll_id,
            QcCheck.decision,
            QcCheck.defects,
            QcCheck.attempt_no,
            Roll.length_m,
            Loom.id,
            Loom.code,
            Loom.name,
            Order.id,
            Order.code,
            Buyer.name,
        )
        .join(Roll, Roll.id == QcCheck.roll_id)
        .join(Loom, Loom.id == Roll.loom_machine_id)
        .join(Order, Order.id == Roll.order_id)
        .join(Buyer, Buyer.id == Order.buyer_id)
        .where(QcCheck.at >= since)
    ).all()

    decided = Counter(r.decision for r in rows)
    metres = defaultdict(lambda: ZERO)
    for r in rows:
        metres[r.decision] += r.length_m
    firsts = [r for r in rows if r.attempt_no == 1]

    by_type: dict[str, dict] = defaultdict(lambda: {"rolls": set(), "count": 0, "points": 0})
    for r in rows:
        for d in r.defects:
            t = by_type[d["type"]]
            t["rolls"].add(r.roll_id)
            t["count"] += d["count"]
            t["points"] += defect_points([d])

    def group(key) -> list[dict]:
        groups: dict[int, dict] = {}
        for r in rows:
            gid, code, name = key(r)
            g = groups.setdefault(
                gid,
                {"id": gid, "code": code, "name": name, "decisions": Counter(), "types": Counter()},
            )
            g["decisions"][r.decision] += 1
            for d in r.defects:
                g["types"][d["type"]] += d["count"]
        out = []
        for g in groups.values():
            checked = sum(g["decisions"].values())
            bad = g["decisions"][QcDecision.rework] + g["decisions"][QcDecision.reject]
            out.append(
                {
                    "id": g["id"],
                    "code": g["code"],
                    "name": g["name"],
                    "checked": checked,
                    "passed": g["decisions"][QcDecision.pass_],
                    "rework": g["decisions"][QcDecision.rework],
                    "rejected": g["decisions"][QcDecision.reject],
                    "defect_rate_pct": _pct(bad, checked),
                    "top_defect": g["types"].most_common(1)[0][0] if g["types"] else None,
                }
            )
        return sorted(out, key=lambda g: (-g["defect_rate_pct"], -g["checked"], g["code"]))

    waiting = db.execute(
        select(func.count(), func.coalesce(func.sum(Roll.length_m), 0)).where(
            Roll.status == RollStatus.awaiting_qc
        )
    ).one()
    return {
        "days": days,
        "waiting": waiting[0],
        "waiting_m": qty(waiting[1]),
        "in_rework": db.scalar(select(func.count()).where(Roll.status == RollStatus.rework)),
        "checked": len(rows),
        "passed": decided[QcDecision.pass_],
        "rework": decided[QcDecision.rework],
        "rejected": decided[QcDecision.reject],
        "passed_m": qty(metres[QcDecision.pass_]),
        "rework_m": qty(metres[QcDecision.rework]),
        "rejected_m": qty(metres[QcDecision.reject]),
        "first_pass_yield_pct": _pct(
            sum(r.decision == QcDecision.pass_ for r in firsts), len(firsts)
        ),
        "by_defect": sorted(
            (
                {"type": k, "rolls": len(v["rolls"]), "count": v["count"], "points": v["points"]}
                for k, v in by_type.items()
            ),
            key=lambda d: (-d["count"], d["type"]),
        ),
        "by_loom": group(lambda r: (r[5], r[6], r[7]))[:20],
        "by_order": group(lambda r: (r[8], r[9], r[10]))[:20],
    }


# --- writes: route-owned, commit once, publish after commit


def _location_id(db: Session, kind: LocationKind) -> int:
    loc_id = db.scalar(select(Location.id).where(Location.kind == kind).order_by(Location.id))
    if not loc_id:
        raise Conflict(f"No '{kind}' location set up in masters")
    return loc_id


def _on_hand(db: Session, roll_id: int, location_id: int) -> Decimal:
    def total(col):
        return db.scalar(
            select(func.coalesce(func.sum(StockMove.qty), 0)).where(
                StockMove.roll_id == roll_id, col == location_id
            )
        )

    return Decimal(total(StockMove.to_location_id)) - Decimal(total(StockMove.from_location_id))


# ledger move for the roll's new home; the roll must be where the ledger says it is
def _move_roll(
    db: Session, roll: Roll, kind: LocationKind, reason: MoveReason, check: QcCheck, user_id: int
) -> None:
    if _on_hand(db, roll.id, roll.location_id) < roll.length_m:
        raise Conflict(
            f"Stock ledger does not show {roll.code} at its location", code="stock_mismatch"
        )
    to = _location_id(db, kind)
    db.add(
        StockMove(
            at=check.at,
            item_kind=ItemKind.fabric,
            roll_id=roll.id,
            qty=roll.length_m,
            unit=Unit.m,
            from_location_id=roll.location_id,
            to_location_id=to,
            reason=reason,
            ref_type="qc_check",
            ref_id=check.id,
            user_id=user_id,
        )
    )
    roll.location_id = to


# one inspection: pass to the shelf, reject to the reject store, rework back to the floor
def inspect(db: Session, roll_id: int, body: InspectIn, user: User) -> dict:
    # production imports this module's transition map, so it is imported here, not at the top
    from app.modules.production import service as production

    def work():
        roll = db.scalar(select(Roll).where(Roll.id == roll_id).with_for_update())
        if not roll:
            raise NotFound(f"Roll {roll_id} not found")
        if roll.status != RollStatus.awaiting_qc:
            raise Conflict(
                f"{roll.code} is {roll.status.replace('_', ' ')}. "
                "Only rolls waiting for QC can be inspected.",
                code="illegal_transition",
            )
        new = DECISION_STATUS[body.decision]
        check_transition(ROLL_TRANSITIONS, roll.status, new)
        attempt = db.scalar(select(func.count()).where(QcCheck.roll_id == roll.id)) + 1
        passed = body.decision == QcDecision.pass_
        check = QcCheck(
            roll_id=roll.id,
            inspector_id=user.id,
            at=_now(),
            attempt_no=attempt,
            decision=body.decision,
            defects=[d.model_dump(mode="json") for d in body.defects],
            shade_band=body.shade_band if passed else None,
            gsm=body.gsm,
            width_cm=body.width_cm,
            notes=body.notes,
        )
        db.add(check)
        db.flush()
        audit.record(
            db,
            user.id,
            str(new),
            "rolls",
            roll.id,
            body.notes,
            {"from": roll.status, "to": new, "qc_check_id": check.id, "attempt": attempt},
        )
        roll.status = new
        rework = None
        if passed:
            _move_roll(db, roll, LocationKind.finished, MoveReason.qc_pass, check, user.id)
            roll.shade_band, roll.passed_at = body.shade_band, check.at
        elif new == RollStatus.rejected:
            _move_roll(db, roll, LocationKind.rejected, MoveReason.qc_reject, check, user.id)
        else:
            fabric = db.scalar(
                select(FabricType)
                .join(Order, Order.fabric_type_id == FabricType.id)
                .where(Order.id == roll.order_id)
            )
            stage = body.rework_stage or fabric.stages[-1].stage
            rework = production.create_rework_work_order(db, roll.id, stage, user.id)
        db.flush()
        row = db.execute(_checks_stmt().where(QcCheck.id == check.id)).one()
        return {
            "roll_id": roll.id,
            "roll_code": roll.code,
            "status": roll.status,
            "check": _check_rows(db, [row])[0],
            "rework_work_order_id": rework.id if rework else None,
            "rework_work_order_code": rework.code if rework else None,
        }

    result = run_once(db, body.idempotency_key, "quality.inspect", work)
    db.commit()
    events.publish("quality", {"type": "inspected", "id": result["roll_id"]})
    events.publish("orders", {"type": "roll", "id": result["check"]["order_id"]})
    events.publish("stock", {"type": "roll", "id": result["roll_id"]})
    if result["rework_work_order_id"]:
        events.publish("machines", {"type": "work_order", "id": result["rework_work_order_id"]})
    return result


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
