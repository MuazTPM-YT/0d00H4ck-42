from datetime import UTC, datetime

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
from app.modules.masters.models import FabricType, Machine
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
)
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
    raise NotImplementedError("production.create_rework_work_order")
