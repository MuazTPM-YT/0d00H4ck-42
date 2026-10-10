from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.core import audit, events
from app.core.enums import Unit
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.inventory.service import location_id
from app.modules.masters.models import Buyer, FabricType, LocationKind, Machine, Shift, Worker
from app.modules.orders.models import Order
from app.modules.quality.models import QcCheck, QcDecision, Roll, RollEvent, RollStatus
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
SUMMARY_KEY = {
    QcDecision.pass_: "passed",
    QcDecision.rework: "rework",
    QcDecision.reject: "rejected",
}


def list_rolls(
    db: Session, page: Page, status: RollStatus | None = None, order_id: int | None = None
) -> dict:
    stmt = select(Roll).order_by(Roll.id.desc())
    if status:
        stmt = stmt.where(Roll.status == status)
    if order_id:
        stmt = stmt.where(Roll.order_id == order_id)
    return paginate(db, stmt, page)


# R11: one inspection, one fact. Row lock so two inspectors cannot decide the same roll
def decide(
    db: Session, roll_id: int, body: QcCheckIn, user_id: int, at: datetime | None = None
) -> dict:
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
        stage = fabric.stages[-1].stage
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
    result = {
        "check": QcCheckOut.model_validate(check),
        "roll": RollOut.model_validate(roll),
        "rework_work_order_id": rework_wo_id,
    }
    db.commit()
    events.publish("quality", {"type": "qc", "id": roll.id})
    events.publish("orders", {"type": "roll", "id": roll.order_id})
    if body.decision in DECISION_MOVE:
        events.publish("stock", {"type": "roll", "id": roll.id})
    return result


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
    raise NotImplementedError("quality.roll_trace")
