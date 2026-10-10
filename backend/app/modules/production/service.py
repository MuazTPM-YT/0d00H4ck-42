from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.enums import Source, Stage, Unit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.idempotency import run_once
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import qty, yarn_kg_for_fabric
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.masters.models import FabricType, Location, LocationKind, Machine
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.production.schemas import (
    MachineEventIn,
    MachineEventOut,
    OutputIn,
    ProductionLogOut,
    RollIn,
    RollOut,
    RollProcessIn,
)
from app.modules.quality.models import Roll, RollBatch, RollEvent, RollStatus
from app.modules.quality.service import ROLL_TRANSITIONS
from app.modules.workforce.service import crew_on_machine, current_shift

WORK_ORDER_TRANSITIONS = {
    WorkOrderStatus.waiting: {WorkOrderStatus.queued},
    WorkOrderStatus.queued: {WorkOrderStatus.running, WorkOrderStatus.waiting},
    WorkOrderStatus.running: {WorkOrderStatus.paused, WorkOrderStatus.done},
    WorkOrderStatus.paused: {WorkOrderStatus.running},
}
# machine status is a reported fact: any change is allowed, repeating the current one is not
MACHINE_TRANSITIONS = {s: set(MachineStatus) - {s} for s in MachineStatus}
STAGE_UNIT = {Stage.spinning: Unit.kg, Stage.weaving: Unit.m, Stage.dyeing: Unit.m}
DOWNTIME = {MachineStatus.breakdown, MachineStatus.maintenance}


def list_work_orders(
    db: Session,
    page: Page,
    status: WorkOrderStatus | None = None,
    order_id: int | None = None,
    machine_id: int | None = None,
) -> dict:
    stmt = select(WorkOrder).order_by(
        WorkOrder.queue_position.nulls_last(), WorkOrder.order_id.desc(), WorkOrder.seq
    )
    if status:
        stmt = stmt.where(WorkOrder.status == status)
    if order_id:
        stmt = stmt.where(WorkOrder.order_id == order_id)
    if machine_id:
        stmt = stmt.where(WorkOrder.machine_id == machine_id)
    return paginate(db, stmt, page)


def _now(at: datetime | None) -> datetime:
    return at or datetime.now(UTC)


# row lock serialises status changes per machine (two feeds, one machine)
def _lock_machine(db: Session, machine_id: int, field: str = "machine_id") -> Machine:
    machine = db.scalar(select(Machine).where(Machine.id == machine_id).with_for_update())
    if not machine or not machine.active:
        raise NotFound(f"Machine {machine_id} not found", field=field)
    return machine


def _lock_work_order(db: Session, work_order_id: int) -> WorkOrder:
    wo = db.scalar(select(WorkOrder).where(WorkOrder.id == work_order_id).with_for_update())
    if not wo:
        raise NotFound(f"Work order {work_order_id} not found", field="work_order_id")
    return wo


def _on_machine(db: Session, machine_id: int, status: WorkOrderStatus) -> WorkOrder | None:
    return db.scalar(
        select(WorkOrder)
        .where(WorkOrder.machine_id == machine_id, WorkOrder.status == status)
        .order_by(WorkOrder.started_at.nulls_last(), WorkOrder.id)
        .limit(1)
    )


def _set_wo_status(db: Session, wo: WorkOrder, new: WorkOrderStatus, user_id, reason=None):
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, new)
    audit.record(
        db, user_id, str(new), "work_orders", wo.id, reason, {"from": wo.status, "to": new}
    )
    wo.status = new


# a machine that can take this stage now: right type, active, not broken down
def _usable_machine(db: Session, machine_id: int, stage: Stage) -> Machine:
    machine = _lock_machine(db, machine_id)
    if machine.type != stage:
        raise Conflict(f"{machine.code} is a {machine.type} machine, not {stage}", "machine_id")
    status = machine_status(db, machine.id)
    if status in DOWNTIME:
        raise Conflict(f"{machine.code} is in {status}", field="machine_id", code="machine_down")
    return machine


def _last_position(db: Session, machine_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.max(WorkOrder.queue_position), 0)).where(
            WorkOrder.machine_id == machine_id, WorkOrder.status == WorkOrderStatus.queued
        )
    )


# write one status event; work order runs only while its machine runs
def _set_machine_status(
    db: Session,
    machine: Machine,
    status: MachineStatus,
    user_id: int | None,
    source: Source = Source.manual,
    reason: str | None = None,
    at: datetime | None = None,
) -> MachineEvent:
    check_transition(MACHINE_TRANSITIONS, machine_status(db, machine.id), status)
    if status in DOWNTIME and not reason:
        raise Unprocessable(f"Give a reason for {status}", field="reason")
    running = _on_machine(db, machine.id, WorkOrderStatus.running)
    if running and status != MachineStatus.running:
        _set_wo_status(db, running, WorkOrderStatus.paused, user_id, reason or f"machine {status}")
    elif not running and status == MachineStatus.running:
        running = _on_machine(db, machine.id, WorkOrderStatus.paused)
        if running:
            _set_wo_status(db, running, WorkOrderStatus.running, user_id, "machine running")
    event = MachineEvent(
        machine_id=machine.id,
        at=_now(at),
        status=status,
        reason=reason,
        work_order_id=running.id if running else None,
        source=source,
        user_id=user_id,
    )
    db.add(event)
    db.flush()
    audit.record(db, user_id, "status", "machines", machine.id, reason, {"status": status})
    return event


def report_machine_event(
    db: Session, body: MachineEventIn, user_id: int, at: datetime | None = None
) -> dict:
    def work():
        machine = _lock_machine(db, body.machine_id)
        event = _set_machine_status(db, machine, body.status, user_id, body.source, body.reason, at)
        return MachineEventOut.model_validate(event)

    result = run_once(db, body.idempotency_key, "production.machine_event", work)
    db.commit()
    events.publish("machines", {"type": "machine_event", "id": body.machine_id})
    return result


def queue_work_order(db: Session, work_order_id: int, machine_id: int, user_id: int) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    order = db.get(Order, wo.order_id)
    if order.status != OrderStatus.confirmed:
        raise Conflict(f"Order {order.code} is {order.status}, not confirmed")
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, WorkOrderStatus.queued)
    machine = _usable_machine(db, machine_id, wo.stage)
    _set_wo_status(db, wo, WorkOrderStatus.queued, user_id)
    wo.machine_id = machine.id
    wo.queue_position = _last_position(db, machine.id) + 1
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


def unqueue_work_order(db: Session, work_order_id: int, user_id: int) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    _set_wo_status(db, wo, WorkOrderStatus.waiting, user_id)
    wo.machine_id = wo.queue_position = None
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


# new order of a machine's queue; ids must be exactly the queued set, else someone else moved it
def reorder_queue(db: Session, machine_id: int, work_order_ids: list[int], user_id: int) -> list:
    _lock_machine(db, machine_id)
    queued = db.scalars(
        select(WorkOrder)
        .where(WorkOrder.machine_id == machine_id, WorkOrder.status == WorkOrderStatus.queued)
        .with_for_update()
    ).all()
    by_id = {wo.id: wo for wo in queued}
    if len(set(work_order_ids)) != len(work_order_ids) or set(work_order_ids) != set(by_id):
        raise Conflict("The queue changed. Reload and try again.", field="work_order_ids")
    for position, wo_id in enumerate(work_order_ids, start=1):
        by_id[wo_id].queue_position = position
    audit.record(db, user_id, "reorder", "machines", machine_id, data={"queue": work_order_ids})
    db.commit()
    events.publish("machines", {"type": "queue", "id": machine_id})
    return [by_id[i] for i in work_order_ids]


def start_work_order(
    db: Session,
    work_order_id: int,
    user_id: int | None,
    at: datetime | None = None,
    source: Source = Source.manual,
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, WorkOrderStatus.running)
    machine = _usable_machine(db, wo.machine_id, wo.stage)
    other = _on_machine(db, machine.id, WorkOrderStatus.running)
    if other:
        raise Conflict(f"{machine.code} is already running {other.code}", field="machine_id")
    _set_wo_status(db, wo, WorkOrderStatus.running, user_id)
    wo.queue_position = None
    wo.started_at = wo.started_at or _now(at)
    db.flush()
    if machine_status(db, machine.id) != MachineStatus.running:
        _set_machine_status(db, machine, MachineStatus.running, user_id, source, at=at)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


# breakdown recovery: queued or paused work order goes to another machine of the same type
def move_work_order(
    db: Session, work_order_id: int, machine_id: int, reason: str, user_id: int
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    if wo.status not in (WorkOrderStatus.queued, WorkOrderStatus.paused):
        raise Conflict(f"Only queued or paused work orders move, {wo.code} is {wo.status}")
    if wo.machine_id == machine_id:
        raise Conflict(f"{wo.code} is already on this machine", field="machine_id")
    machine = _usable_machine(db, machine_id, wo.stage)
    audit.record(
        db, user_id, "move", "work_orders", wo.id, reason, {"from": wo.machine_id, "to": machine.id}
    )
    wo.machine_id = machine.id
    if wo.status == WorkOrderStatus.queued:
        wo.queue_position = _last_position(db, machine.id) + 1
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


def finish_work_order(
    db: Session,
    work_order_id: int,
    user_id: int | None,
    at: datetime | None = None,
    source: Source = Source.manual,
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    _set_wo_status(db, wo, WorkOrderStatus.done, user_id)
    wo.finished_at = _now(at)
    db.flush()
    machine = _lock_machine(db, wo.machine_id)
    if machine_status(db, machine.id) == MachineStatus.running:
        _set_machine_status(db, machine, MachineStatus.idle, user_id, source, at=at)
    _consume_rest(db, wo, user_id, _now(at))
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    events.publish("orders", {"type": "work_order", "id": wo.order_id})
    return wo


def _add_log(
    db: Session,
    wo: WorkOrder,
    machine_id: int,
    quantity,
    at: datetime,
    source: Source,
    shift_id: int | None = None,
    worker_id: int | None = None,
) -> ProductionLog:
    log = ProductionLog(
        work_order_id=wo.id,
        machine_id=machine_id,
        shift_id=shift_id or current_shift(db, at)[1].id,
        worker_id=worker_id or crew_on_machine(db, machine_id, at),
        qty=quantity,
        unit=wo.unit,
        at=at,
        source=source,
    )
    db.add(log)
    db.flush()
    return log


# one intake for tablet, scanner and machine counter; a feed sends only machine + qty
def log_output(db: Session, body: OutputIn, user_id: int, at: datetime | None = None) -> dict:
    def work():
        machine = _lock_machine(db, body.machine_id)
        status = machine_status(db, machine.id)
        if status in DOWNTIME:
            raise Conflict(
                f"{machine.code} is in {status}. Output cannot be logged on a stopped machine.",
                field="machine_id",
                code="machine_down",
            )
        if body.work_order_id:
            wo = db.get(WorkOrder, body.work_order_id)
            if not wo or wo.machine_id != machine.id:
                raise Conflict(f"That work order is not on {machine.code}", "work_order_id")
        else:
            wo = _on_machine(db, machine.id, WorkOrderStatus.running) or _on_machine(
                db, machine.id, WorkOrderStatus.paused
            )
            if not wo:
                raise Conflict(f"No work order is running on {machine.code}", "machine_id")
        if wo.status not in (WorkOrderStatus.running, WorkOrderStatus.paused):
            raise Conflict(f"{wo.code} is {wo.status}, output needs a started job", "work_order_id")
        log = _add_log(
            db,
            wo,
            machine.id,
            body.qty,
            _now(body.at or at),
            body.source,
            body.shift_id,
            body.worker_id,
        )
        return ProductionLogOut.model_validate(log)

    result = run_once(db, body.idempotency_key, "production.output", work)
    db.commit()
    events.publish("machines", {"type": "output", "id": body.machine_id})
    events.publish("orders", {"type": "output", "id": result["work_order_id"]})
    return result


def _location_id(db: Session, kind: LocationKind) -> int:
    return db.scalar(select(Location.id).where(Location.kind == kind).order_by(Location.id))


# per yarn batch for one work order: kg issued (net of returns) and kg still on the floor
def _wip_yarn(db: Session, work_order_id: int) -> dict[int, dict[str, Decimal]]:
    wip = set(db.scalars(select(Location.id).where(Location.kind == LocationKind.wip)))
    moves = db.execute(
        select(
            StockMove.yarn_batch_id,
            StockMove.reason,
            StockMove.from_location_id,
            StockMove.to_location_id,
            StockMove.qty,
        ).where(
            StockMove.ref_type == "work_order",
            StockMove.ref_id == work_order_id,
            StockMove.item_kind == ItemKind.yarn,
        )
    ).all()
    out = defaultdict(lambda: {"issued": Decimal(0), "left": Decimal(0)})
    for batch_id, reason, frm, to, kg in moves:
        if to in wip:
            out[batch_id]["issued"] += kg
            out[batch_id]["left"] += kg
        if frm in wip:
            out[batch_id]["left"] -= kg
            if reason == MoveReason.return_:
                out[batch_id]["issued"] -= kg
    return dict(out)


# proportional split; the biggest share takes the rounding remainder so rows sum exactly
def split_kg(total: Decimal, weights: dict[int, Decimal]) -> dict[int, Decimal]:
    whole = sum(weights.values())
    biggest = max(weights, key=lambda k: (weights[k], -k))
    out = {k: qty(total * w / whole) for k, w in weights.items() if k != biggest}
    out[biggest] = total - sum(out.values())
    return {k: v for k, v in out.items() if v > 0}


# job done: yarn still on the floor for it is used up (WIP -> production)
def _consume_rest(db: Session, wo: WorkOrder, user_id: int | None, at: datetime) -> None:
    left = {b: v["left"] for b, v in _wip_yarn(db, wo.id).items() if v["left"] > 0}
    if not left:
        return
    wip, used = _location_id(db, LocationKind.wip), _location_id(db, LocationKind.consumed)
    for batch_id, kg in left.items():
        db.add(
            StockMove(
                at=at,
                item_kind=ItemKind.yarn,
                yarn_batch_id=batch_id,
                qty=kg,
                unit=Unit.kg,
                from_location_id=wip,
                to_location_id=used,
                reason=MoveReason.consume,
                ref_type="work_order",
                ref_id=wo.id,
                user_id=user_id,
            )
        )


def _set_roll_status(db: Session, roll: Roll, new: RollStatus, user_id: int | None) -> None:
    check_transition(ROLL_TRANSITIONS, roll.status, new)
    audit.record(db, user_id, str(new), "rolls", roll.id, data={"from": roll.status, "to": new})
    roll.status = new


# after the last stage of the fabric's route the roll waits for QC
def _after_stage(db: Session, roll: Roll, stage: Stage, user_id: int | None) -> None:
    order = db.get(Order, roll.order_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    if fabric.stages[-1].stage == stage:
        _set_roll_status(db, roll, RollStatus.awaiting_qc, user_id)


def _publish_roll(result: dict) -> None:
    events.publish("machines", {"type": "roll", "id": result["id"]})
    events.publish("orders", {"type": "roll", "id": result["order_id"]})
    if result["status"] == RollStatus.awaiting_qc:
        events.publish("quality", {"type": "roll", "id": result["id"]})


# weaver cuts a roll off the loom: new identity, yarn lineage, fabric enters WIP
def cut_roll(db: Session, body: RollIn, user_id: int | None, at: datetime | None = None) -> dict:
    def work():
        wo = _lock_work_order(db, body.work_order_id)
        if wo.stage != Stage.weaving or wo.roll_id:
            raise Conflict("Rolls are cut from a weaving work order", field="work_order_id")
        if wo.status not in (WorkOrderStatus.running, WorkOrderStatus.paused):
            raise Conflict(f"{wo.code} is {wo.status}, cut rolls from a started job")
        issued = {b: v["issued"] for b, v in _wip_yarn(db, wo.id).items() if v["issued"] > 0}
        if not issued:
            raise Conflict(
                f"No yarn issued to {wo.code} yet. The store issues yarn first.",
                field="work_order_id",
                code="no_yarn_issued",
            )
        when = _now(at)
        order = db.get(Order, wo.order_id)
        fabric = db.get(FabricType, order.fabric_type_id)
        roll = Roll(
            code=next_code(db, "R"),
            order_id=order.id,
            work_order_id=wo.id,
            loom_machine_id=wo.machine_id,
            shift_id=body.shift_id or current_shift(db, when)[1].id,
            weaver_id=body.weaver_id or crew_on_machine(db, wo.machine_id, when),
            length_m=body.length_m,
            status=RollStatus.in_process,
            location_id=_location_id(db, LocationKind.wip),
        )
        db.add(roll)
        db.flush()
        kg = yarn_kg_for_fabric(body.length_m, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
        for batch_id, share in split_kg(kg, issued).items():
            db.add(RollBatch(roll_id=roll.id, yarn_batch_id=batch_id, kg=share))
        db.add(
            RollEvent(
                roll_id=roll.id,
                at=when,
                kind="woven",
                machine_id=wo.machine_id,
                work_order_id=wo.id,
            )
        )
        db.add(
            StockMove(
                at=when,
                item_kind=ItemKind.fabric,
                roll_id=roll.id,
                qty=body.length_m,
                unit=Unit.m,
                from_location_id=_location_id(db, LocationKind.consumed),
                to_location_id=roll.location_id,
                reason=MoveReason.produce,
                ref_type="work_order",
                ref_id=wo.id,
                user_id=user_id,
                source=body.source,
            )
        )
        audit.record(db, user_id, "create", "rolls", roll.id, data={"work_order_id": wo.id})
        _after_stage(db, roll, wo.stage, user_id)
        db.flush()
        return RollOut.model_validate(roll)

    result = run_once(db, body.idempotency_key, "production.roll", work)
    db.commit()
    _publish_roll(result)
    return result


# a later stage (dyeing) or a rework job takes a whole roll: roll event + output log, one fact
def process_roll(
    db: Session, roll_id: int, body: RollProcessIn, user_id: int | None, at: datetime | None = None
) -> dict:
    def work():
        roll = db.scalar(select(Roll).where(Roll.id == roll_id).with_for_update())
        if not roll:
            raise NotFound(f"Roll {roll_id} not found")
        wo = _lock_work_order(db, body.work_order_id)
        if wo.order_id != roll.order_id:
            raise Conflict(f"{roll.code} belongs to another order", field="work_order_id")
        if wo.status != WorkOrderStatus.running:
            raise Conflict(f"Start {wo.code} before processing rolls", field="work_order_id")
        if wo.roll_id:
            if wo.roll_id != roll.id:
                raise Conflict(f"{wo.code} is rework for another roll", field="work_order_id")
            expected = RollStatus.rework
        elif wo.stage != Stage.dyeing:
            raise Conflict("Only dyeing and rework jobs process finished rolls", "work_order_id")
        else:
            expected = RollStatus.in_process
        if roll.status != expected:
            raise Conflict(f"{roll.code} is {roll.status}")
        seen = select(RollEvent.id).where(
            RollEvent.roll_id == roll.id, RollEvent.work_order_id == wo.id
        )
        if db.scalar(seen):
            raise Conflict(f"{roll.code} already went through {wo.code}")
        when = _now(at)
        db.add(
            RollEvent(
                roll_id=roll.id,
                at=when,
                kind="rework" if wo.roll_id else "dyed",
                machine_id=wo.machine_id,
                work_order_id=wo.id,
            )
        )
        _add_log(db, wo, wo.machine_id, roll.length_m, when, body.source)
        if wo.roll_id:
            _set_roll_status(db, roll, RollStatus.awaiting_qc, user_id)
        else:
            _after_stage(db, roll, wo.stage, user_id)
        db.flush()
        return RollOut.model_validate(roll)

    result = run_once(db, body.idempotency_key, "production.roll_process", work)
    db.commit()
    _publish_roll(result)
    return result


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# one waiting work order per route stage; safe to call twice (returns the existing set)
def create_work_orders(db: Session, order_id: int, user_id: int | None) -> list[WorkOrder]:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    existing = db.scalars(
        select(WorkOrder)
        .where(WorkOrder.order_id == order_id, WorkOrder.roll_id.is_(None))
        .order_by(WorkOrder.seq)
    ).all()
    if existing:
        return list(existing)
    fabric = db.get(FabricType, order.fabric_type_id)
    yarn_kg = yarn_kg_for_fabric(order.qty_m, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
    work_orders = []
    for st in fabric.stages:
        unit = STAGE_UNIT[st.stage]
        wo = WorkOrder(
            code=next_code(db, "WO"),
            order_id=order.id,
            stage=st.stage,
            seq=st.seq,
            planned_qty=yarn_kg if unit == Unit.kg else order.qty_m,
            unit=unit,
            status=WorkOrderStatus.waiting,
        )
        db.add(wo)
        work_orders.append(wo)
    db.flush()
    for wo in work_orders:
        audit.record(
            db,
            user_id,
            "create",
            "work_orders",
            wo.id,
            data={"order_id": order.id, "stage": wo.stage},
        )
    return work_orders


# latest machine_events row, or off when the machine never reported
def machine_status(db: Session, machine_id: int) -> MachineStatus:
    status = db.scalar(
        select(MachineEvent.status)
        .where(MachineEvent.machine_id == machine_id)
        .order_by(MachineEvent.at.desc(), MachineEvent.id.desc())
        .limit(1)
    )
    return status or MachineStatus.off


# per stage: planned, produced so far, unit
def order_progress(db: Session, order_id: int) -> dict[Stage, dict]:
    rows = db.execute(
        select(
            WorkOrder.stage,
            WorkOrder.planned_qty,
            WorkOrder.unit,
            func.coalesce(func.sum(ProductionLog.qty), 0),
        )
        .outerjoin(ProductionLog, ProductionLog.work_order_id == WorkOrder.id)
        .where(WorkOrder.order_id == order_id, WorkOrder.roll_id.is_(None))
        .group_by(WorkOrder.id)
        .order_by(WorkOrder.seq)
    ).all()
    return {
        stage: {"planned": planned, "produced": qty(produced), "unit": unit}
        for stage, planned, unit, produced in rows
    }


# new work order for one roll sent back by QC; roll_id set, seq after the original stage
def create_rework_work_order(db: Session, roll_id: int, stage: Stage, user_id: int) -> WorkOrder:
    roll = db.get(Roll, roll_id)
    if not roll:
        raise NotFound(f"Roll {roll_id} not found")
    if roll.status != RollStatus.rework:
        raise Conflict(f"{roll.code} is {roll.status}, not rework")
    order = db.get(Order, roll.order_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    seq = next((s.seq for s in fabric.stages if s.stage == stage), None)
    if stage == Stage.spinning or seq is None:
        raise Unprocessable(f"{stage} cannot rework a roll of {fabric.code}", field="stage")
    open_wo = db.scalar(
        select(WorkOrder).where(
            WorkOrder.roll_id == roll.id, WorkOrder.status != WorkOrderStatus.done
        )
    )
    if open_wo:
        return open_wo
    wo = WorkOrder(
        code=next_code(db, "WO"),
        order_id=order.id,
        stage=stage,
        seq=seq,
        planned_qty=roll.length_m,
        unit=Unit.m,
        status=WorkOrderStatus.waiting,
        roll_id=roll.id,
    )
    db.add(wo)
    db.flush()
    audit.record(db, user_id, "create", "work_orders", wo.id, data={"rework_roll_id": roll.id})
    return wo
