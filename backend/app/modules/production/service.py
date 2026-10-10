from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
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
from app.modules.masters.models import FabricType, Location, LocationKind, Machine, Worker
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
    ProcessWaitingIn,
    ProductionLogOut,
    RollIn,
    RollOut,
    RollProcessIn,
    WorkOrderOut,
)
from app.modules.quality.models import Roll, RollBatch, RollEvent, RollStatus
from app.modules.quality.service import ROLL_TRANSITIONS
from app.modules.workforce.models import CrewAssignment
from app.modules.workforce.schemas import IST
from app.modules.workforce.service import crew_on_machine, current_shift, day_start, payroll_open

# weaving and dyeing plan this much over the order so rejected rolls still leave enough metres
PROCESS_ALLOWANCE = Decimal("0.05")

WORK_ORDER_TRANSITIONS = {
    WorkOrderStatus.waiting: {WorkOrderStatus.queued},
    WorkOrderStatus.queued: {WorkOrderStatus.running, WorkOrderStatus.waiting},
    WorkOrderStatus.running: {WorkOrderStatus.paused, WorkOrderStatus.done},
    WorkOrderStatus.paused: {WorkOrderStatus.running, WorkOrderStatus.done},
}
# machine status is a reported fact: any change is allowed, repeating the current one is not
MACHINE_TRANSITIONS = {s: set(MachineStatus) - {s} for s in MachineStatus}
STAGE_UNIT = {Stage.spinning: Unit.kg, Stage.weaving: Unit.m, Stage.dyeing: Unit.m}
DOWNTIME = {MachineStatus.breakdown, MachineStatus.maintenance}
FLOW = {Stage.spinning: 0, Stage.weaving: 1, Stage.dyeing: 2}
ACTIVE = (WorkOrderStatus.running, WorkOrderStatus.paused)
# below this many metres the loom leftover is not worth a roll
MIN_TAIL_M = Decimal(1)
# auto-pull starts work only on a machine that is on and not stopped
PULLABLE = (MachineStatus.running, MachineStatus.idle)


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


# a cancelled or closed order takes no more work: no start, no output, no new rolls
def _require_open_order(db: Session, wo: WorkOrder) -> None:
    order = db.get(Order, wo.order_id)
    if order.status != OrderStatus.confirmed:
        raise Conflict(
            f"Order {order.code} is {order.status}; {wo.code} cannot run",
            field="work_order_id",
            code="order_not_open",
        )


def _on_machine(db: Session, machine_id: int, status: WorkOrderStatus) -> WorkOrder | None:
    return db.scalar(
        select(WorkOrder)
        .where(WorkOrder.machine_id == machine_id, WorkOrder.status == status)
        .order_by(WorkOrder.started_at.nulls_last(), WorkOrder.id)
        .limit(1)
    )


def _active_jobs(db: Session, machine_id: int) -> list[WorkOrder]:
    return list(
        db.scalars(
            select(WorkOrder)
            .where(WorkOrder.machine_id == machine_id, WorkOrder.status.in_(ACTIVE))
            .order_by(WorkOrder.id)
        )
    )


# the order's route jobs (not rework), in stage order
def _mains(db: Session, order_id: int) -> list[WorkOrder]:
    return list(
        db.scalars(
            select(WorkOrder)
            .where(WorkOrder.order_id == order_id, WorkOrder.roll_id.is_(None))
            .order_by(WorkOrder.seq)
        )
    )


def _rolls_waiting(db: Session, order_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Roll)
        .where(Roll.order_id == order_id, Roll.status == RollStatus.in_process)
    )


def _produced(db: Session, work_order_id: int) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(ProductionLog.qty), 0)).where(
            ProductionLog.work_order_id == work_order_id
        )
    )


def _rolled(db: Session, work_order_id: int) -> Decimal:
    return db.scalar(
        select(func.coalesce(func.sum(Roll.length_m), 0)).where(Roll.work_order_id == work_order_id)
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


def _busy(machine: Machine, other: WorkOrder) -> Conflict:
    return Conflict(
        f"{machine.code} already has {other.code} ({other.status})",
        field="machine_id",
        code="machine_busy",
    )


def _last_position(db: Session, machine_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.max(WorkOrder.queue_position), 0)).where(
            WorkOrder.machine_id == machine_id, WorkOrder.status == WorkOrderStatus.queued
        )
    )


# rework jumps the line: it goes to the head and everyone else steps back one
def _place_in_queue(db: Session, wo: WorkOrder, machine_id: int) -> None:
    if not wo.roll_id:
        wo.queue_position = _last_position(db, machine_id) + 1
        return
    behind = db.scalars(
        select(WorkOrder)
        .where(
            WorkOrder.machine_id == machine_id,
            WorkOrder.status == WorkOrderStatus.queued,
            WorkOrder.id != wo.id,
        )
        .with_for_update()
    )
    for other in behind:
        other.queue_position = (other.queue_position or 0) + 1
    wo.queue_position = 1


# the job the last stop hit; else whatever sits paused here (a job moved in while paused)
def _paused_by_downtime(db: Session, machine_id: int) -> WorkOrder | None:
    hit = db.scalar(
        select(MachineEvent.work_order_id)
        .where(MachineEvent.machine_id == machine_id, MachineEvent.work_order_id.is_not(None))
        .order_by(MachineEvent.at.desc(), MachineEvent.id.desc())
        .limit(1)
    )
    wo = db.get(WorkOrder, hit) if hit else None
    if wo and wo.machine_id == machine_id and wo.status == WorkOrderStatus.paused:
        return wo
    return _on_machine(db, machine_id, WorkOrderStatus.paused)


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
        running = _paused_by_downtime(db, machine.id)
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
        if body.status in PULLABLE:
            advance(db, user_id, at)
        return MachineEventOut.model_validate(event)

    result = run_once(db, body.idempotency_key, "production.machine_event", work)
    db.commit()
    events.publish("machines", {"type": "machine_event", "id": body.machine_id})
    return result


def queue_work_order(
    db: Session, work_order_id: int, machine_id: int, user_id: int, at: datetime | None = None
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    order = db.get(Order, wo.order_id)
    if order.status != OrderStatus.confirmed:
        raise Conflict(f"Order {order.code} is {order.status}, not confirmed")
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, WorkOrderStatus.queued)
    machine = _usable_machine(db, machine_id, wo.stage)
    _set_wo_status(db, wo, WorkOrderStatus.queued, user_id)
    wo.machine_id = machine.id
    _place_in_queue(db, wo, machine.id)
    db.flush()
    pull_next(db, machine.id, user_id, at)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


def unqueue_work_order(
    db: Session, work_order_id: int, user_id: int, at: datetime | None = None
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    machine_id = wo.machine_id
    _set_wo_status(db, wo, WorkOrderStatus.waiting, user_id)
    wo.machine_id = wo.queue_position = None
    db.flush()
    if machine_id:
        pull_next(db, machine_id, user_id, at)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


# new order of a machine's queue; ids must be exactly the queued set, else someone else moved it
def reorder_queue(
    db: Session,
    machine_id: int,
    work_order_ids: list[int],
    user_id: int,
    at: datetime | None = None,
) -> list:
    _lock_machine(db, machine_id)
    queued = db.scalars(
        select(WorkOrder)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(
            WorkOrder.machine_id == machine_id,
            WorkOrder.status == WorkOrderStatus.queued,
            Order.status == OrderStatus.confirmed,
        )
        .with_for_update(of=WorkOrder)
    ).all()
    by_id = {wo.id: wo for wo in queued}
    if len(set(work_order_ids)) != len(work_order_ids) or set(work_order_ids) != set(by_id):
        raise Conflict("The queue changed. Reload and try again.", field="work_order_ids")
    for position, wo_id in enumerate(work_order_ids, start=1):
        by_id[wo_id].queue_position = position
    audit.record(db, user_id, "reorder", "machines", machine_id, data={"queue": work_order_ids})
    db.flush()
    pull_next(db, machine_id, user_id, at)
    db.commit()
    events.publish("machines", {"type": "queue", "id": machine_id})
    return [by_id[i] for i in work_order_ids]


def _no_yarn(db: Session, order_id: int) -> Conflict:
    first = _mains(db, order_id)[0]
    return Conflict(
        f"The store issues yarn to {first.code} first", field="work_order_id", code="no_yarn_issued"
    )


# route order: first stage needs yarn, a later one needs the one before started (dyeing: a roll)
def _check_stage_start(db: Session, wo: WorkOrder, order: Order) -> None:
    earlier = [m for m in _mains(db, order.id) if m.seq < wo.seq]
    if not earlier:
        if not _order_issued(db, order.id):
            raise _no_yarn(db, order.id)
        return
    prev = earlier[-1]
    if prev.status not in (*ACTIVE, WorkOrderStatus.done):
        raise Conflict(f"Start {prev.code} ({prev.stage}) first", code="stage_order")
    if wo.stage == Stage.dyeing and not _rolls_waiting(db, order.id):
        raise Conflict(
            f"No woven roll of {order.code} is waiting for dyeing", code="no_rolls_waiting"
        )


# every rule is checked before anything changes, so a refusal leaves no trace
def _start(
    db: Session, wo: WorkOrder, user_id: int | None, at: datetime | None, source: Source
) -> WorkOrder:
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, WorkOrderStatus.running)
    _require_open_order(db, wo)
    machine = _usable_machine(db, wo.machine_id, wo.stage)
    others = [j for j in _active_jobs(db, machine.id) if j.id != wo.id]
    # rework pre-empts the route job on its machine; anything else waits for a free machine
    if others and not (wo.roll_id and all(j.roll_id is None for j in others)):
        raise _busy(machine, others[0])
    if wo.roll_id is None and wo.status == WorkOrderStatus.queued:
        _check_stage_start(db, wo, db.get(Order, wo.order_id))
    for job in others:
        if job.status == WorkOrderStatus.running:
            roll_code = db.scalar(select(Roll.code).where(Roll.id == wo.roll_id))
            _set_wo_status(db, job, WorkOrderStatus.paused, user_id, f"rework {roll_code}")
    db.flush()  # free the running slot before taking it (unique index per machine)
    _set_wo_status(db, wo, WorkOrderStatus.running, user_id)
    wo.queue_position = None
    wo.started_at = wo.started_at or _now(at)
    db.flush()
    if machine_status(db, machine.id) != MachineStatus.running:
        _set_machine_status(db, machine, MachineStatus.running, user_id, source, at=at)
    return wo


def start_work_order(
    db: Session,
    work_order_id: int,
    user_id: int | None,
    at: datetime | None = None,
    source: Source = Source.manual,
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    _start(db, wo, user_id, at, source)
    advance(db, user_id, at)
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
    busy = _active_jobs(db, machine.id)
    if wo.status == WorkOrderStatus.paused and busy:
        raise _busy(machine, busy[0])
    old = wo.machine_id
    audit.record(db, user_id, "move", "work_orders", wo.id, reason, {"from": old, "to": machine.id})
    wo.machine_id = machine.id
    if wo.status == WorkOrderStatus.queued:
        _place_in_queue(db, wo, machine.id)
    db.flush()
    for mid in (old, machine.id):
        pull_next(db, mid, user_id)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    return wo


def _went_through(db: Session, roll_id: int, work_order_id: int) -> bool:
    # only processing events count: QC's rework event also names this job
    return (
        db.scalar(
            select(RollEvent.id)
            .where(
                RollEvent.roll_id == roll_id,
                RollEvent.work_order_id == work_order_id,
                RollEvent.kind.in_(["dyed", "rework"]),
            )
            .limit(1)
        )
        is not None
    )


# why this job may not be done yet, or None
def _finish_blocker(db: Session, wo: WorkOrder) -> Conflict | None:
    if wo.roll_id:
        if not _went_through(db, wo.roll_id, wo.id):
            roll_code = db.scalar(select(Roll.code).where(Roll.id == wo.roll_id))
            return Conflict(f"Process {roll_code} first", code="roll_not_processed")
        return None
    for prev in _mains(db, wo.order_id):
        if prev.seq < wo.seq and prev.status != WorkOrderStatus.done:
            return Conflict(f"Finish {prev.code} ({prev.stage}) first", code="stage_order")
    if wo.stage == Stage.dyeing:
        waiting = _rolls_waiting(db, wo.order_id)
        if waiting:
            return Conflict(f"{waiting} woven rolls still wait for dyeing", code="rolls_waiting")
    return None


def _finish(
    db: Session, wo: WorkOrder, user_id: int | None, at: datetime | None, source: Source
) -> None:
    check_transition(WORK_ORDER_TRANSITIONS, wo.status, WorkOrderStatus.done)
    blocker = _finish_blocker(db, wo)
    if blocker:
        raise blocker
    when = _now(at)
    if wo.stage == Stage.weaving and wo.roll_id is None:
        tail = qty(_produced(db, wo.id) - _rolled(db, wo.id))
        if tail >= MIN_TAIL_M:
            _cut(db, wo, tail, user_id, when, source)
    was_running = wo.status == WorkOrderStatus.running
    _set_wo_status(db, wo, WorkOrderStatus.done, user_id)
    wo.finished_at = when
    db.flush()  # free the running slot before a pre-empted job takes it back
    # a paused job is done while its machine is down or busy: no machine event for that
    if was_running:
        machine = _lock_machine(db, wo.machine_id)
        if machine_status(db, machine.id) == MachineStatus.running:
            back = _on_machine(db, machine.id, WorkOrderStatus.paused) if wo.roll_id else None
            if back:
                _set_wo_status(db, back, WorkOrderStatus.running, user_id, "rework done")
                db.flush()
            else:
                _set_machine_status(db, machine, MachineStatus.idle, user_id, source, at=at)
    _consume_rest(db, wo, user_id, when)


# finish every route stage of the order that has nothing left to do, earliest first
def _settle(
    db: Session,
    order_id: int,
    user_id: int | None,
    at: datetime | None,
    source: Source = Source.manual,
) -> int:
    finished = 0
    for wo in _mains(db, order_id):
        if wo.status not in ACTIVE:
            continue
        ready = wo.stage == Stage.dyeing or _produced(db, wo.id) >= wo.planned_qty
        if ready and _finish_blocker(db, wo) is None:
            _finish(db, wo, user_id, at, source)
            finished += 1
    return finished


def finish_work_order(
    db: Session,
    work_order_id: int,
    user_id: int | None,
    at: datetime | None = None,
    source: Source = Source.manual,
) -> WorkOrder:
    wo = _lock_work_order(db, work_order_id)
    _finish(db, wo, user_id, at, source)
    _settle(db, wo.order_id, user_id, at, source)
    advance(db, user_id, at)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": wo.id})
    events.publish("orders", {"type": "work_order", "id": wo.order_id})
    events.publish("quality", {"type": "work_order", "id": wo.id})
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
        if wo.status not in ACTIVE:
            raise Conflict(f"{wo.code} is {wo.status}, output needs a started job", "work_order_id")
        _require_open_order(db, wo)
        if not _order_issued(db, wo.order_id):
            raise _no_yarn(db, wo.order_id)
        when = _now(body.at or at)
        payroll_open(db, when.astimezone(IST).date())  # piece pay for that day is settled
        log = _add_log(
            db,
            wo,
            machine.id,
            body.qty,
            when,
            body.source,
            body.shift_id,
            body.worker_id,
        )
        # a buffered counter time stamps the log only; finishing happens now
        if _settle(db, wo.order_id, user_id, at, body.source):
            advance(db, user_id, at)
        return ProductionLogOut.model_validate(log)

    result = run_once(db, body.idempotency_key, "production.output", work)
    db.commit()
    events.publish("machines", {"type": "output", "id": body.machine_id})
    events.publish("orders", {"type": "output", "id": result["work_order_id"]})
    events.publish("quality", {"type": "output", "id": result["work_order_id"]})
    return result


def _location_id(db: Session, kind: LocationKind) -> int:
    return db.scalar(select(Location.id).where(Location.kind == kind).order_by(Location.id))


# per yarn batch for some work orders: kg issued (net of returns) and kg still on the floor
def _wip_yarn(db: Session, *work_order_ids: int) -> dict[int, dict[str, Decimal]]:
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
            StockMove.ref_id.in_(work_order_ids),
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


# net kg per batch the store gave any route job of the order (yarn goes to the first stage)
def _order_issued(db: Session, order_id: int) -> dict[int, Decimal]:
    ids = [wo.id for wo in _mains(db, order_id)]
    return {b: v["issued"] for b, v in _wip_yarn(db, *ids).items() if v["issued"] > 0}


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


# new roll identity off a loom job: yarn lineage, fabric enters WIP. Never more than was woven.
def _cut(
    db: Session,
    wo: WorkOrder,
    length: Decimal,
    user_id: int | None,
    when: datetime,
    source: Source,
    shift_id: int | None = None,
    weaver_id: int | None = None,
) -> Roll:
    if wo.stage != Stage.weaving or wo.roll_id:
        raise Conflict("Rolls are cut from a weaving work order", field="work_order_id")
    if wo.status not in ACTIVE:
        raise Conflict(f"{wo.code} is {wo.status}, cut rolls from a started job")
    issued = _order_issued(db, wo.order_id)
    if not issued:
        raise _no_yarn(db, wo.order_id)
    free = _produced(db, wo.id) - _rolled(db, wo.id)
    if length > free:
        raise Conflict(
            f"Only {qty(max(free, Decimal(0)))} m woven on {wo.code} is not in a roll yet",
            field="length_m",
            code="more_than_woven",
        )
    order = db.get(Order, wo.order_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    roll = Roll(
        code=next_code(db, "R"),
        order_id=order.id,
        work_order_id=wo.id,
        loom_machine_id=wo.machine_id,
        shift_id=shift_id or current_shift(db, when)[1].id,
        weaver_id=weaver_id or crew_on_machine(db, wo.machine_id, when),
        length_m=length,
        status=RollStatus.in_process,
        location_id=_location_id(db, LocationKind.wip),
    )
    db.add(roll)
    db.flush()
    kg = yarn_kg_for_fabric(length, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
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
            qty=length,
            unit=Unit.m,
            from_location_id=_location_id(db, LocationKind.consumed),
            to_location_id=roll.location_id,
            reason=MoveReason.produce,
            ref_type="work_order",
            ref_id=wo.id,
            user_id=user_id,
            source=source,
        )
    )
    audit.record(db, user_id, "create", "rolls", roll.id, data={"work_order_id": wo.id})
    _after_stage(db, roll, wo.stage, user_id)
    db.flush()
    return roll


# weaver cuts a roll off the loom
def cut_roll(db: Session, body: RollIn, user_id: int | None, at: datetime | None = None) -> dict:
    def work():
        wo = _lock_work_order(db, body.work_order_id)
        _require_open_order(db, wo)
        roll = _cut(
            db, wo, body.length_m, user_id, _now(at), body.source, body.shift_id, body.weaver_id
        )
        advance(db, user_id, at)  # a first woven roll can let dyeing start
        return RollOut.model_validate(roll)

    result = run_once(db, body.idempotency_key, "production.roll", work)
    db.commit()
    _publish_roll(result)
    return result


# a later stage (dyeing) or a rework job takes a whole roll: roll event + output log, one fact
def _process(
    db: Session,
    roll: Roll,
    wo: WorkOrder,
    user_id: int | None,
    at: datetime | None,
    source: Source,
) -> None:
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
    if _went_through(db, roll.id, wo.id):
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
    _add_log(db, wo, wo.machine_id, roll.length_m, when, source)
    if wo.roll_id:
        _set_roll_status(db, roll, RollStatus.awaiting_qc, user_id)
        db.flush()
        # the rework job had one roll to do: it is done, a later rework gets a new job
        _finish(db, wo, user_id, at, source)
    else:
        _after_stage(db, roll, wo.stage, user_id)
    db.flush()


def process_roll(
    db: Session, roll_id: int, body: RollProcessIn, user_id: int | None, at: datetime | None = None
) -> dict:
    def work():
        roll = db.scalar(select(Roll).where(Roll.id == roll_id).with_for_update())
        if not roll:
            raise NotFound(f"Roll {roll_id} not found")
        wo = _lock_work_order(db, body.work_order_id)
        _require_open_order(db, wo)
        _process(db, roll, wo, user_id, at, body.source)
        _settle(db, wo.order_id, user_id, at, body.source)
        advance(db, user_id, at)
        return RollOut.model_validate(roll)

    result = run_once(db, body.idempotency_key, "production.roll_process", work)
    db.commit()
    _publish_roll(result)
    return result


# batch dyeing: every woven roll of the order that waits goes through this job at once
def process_waiting(
    db: Session,
    work_order_id: int,
    body: ProcessWaitingIn,
    user_id: int | None,
    at: datetime | None = None,
) -> dict:
    def work():
        wo = _lock_work_order(db, work_order_id)
        if wo.stage != Stage.dyeing or wo.roll_id:
            raise Conflict("Only a dyeing job dyes the waiting rolls", field="work_order_id")
        rolls = db.scalars(
            select(Roll)
            .where(Roll.order_id == wo.order_id, Roll.status == RollStatus.in_process)
            .order_by(Roll.id)
            .with_for_update()
        ).all()
        for roll in rolls:
            _process(db, roll, wo, user_id, at, body.source)
        _settle(db, wo.order_id, user_id, at, body.source)
        advance(db, user_id, at)
        return {"work_order_id": wo.id, "processed": len(rolls)}

    result = run_once(db, body.idempotency_key, "production.process_waiting", work)
    db.commit()
    events.publish("machines", {"type": "work_order", "id": work_order_id})
    events.publish("orders", {"type": "work_order", "id": work_order_id})
    events.publish("quality", {"type": "work_order", "id": work_order_id})
    return result


# one pass over time-ordered (at, status) pairs; time before the first event counts as off
def status_durations(
    events: list[tuple[datetime, str]], start: datetime, end: datetime
) -> dict[str, float]:
    seconds = {s.value: 0.0 for s in MachineStatus}
    points = list(events)
    if not points or points[0][0] > start:
        points.insert(0, (start, MachineStatus.off))
    for (at, status), (next_at, _) in zip(points, [*points[1:], (end, None)], strict=True):
        a, b = max(at, start), min(next_at, end)
        if b > a:
            seconds[status] += (b - a).total_seconds()
    return seconds


def _sum_by(db: Session, key, *where) -> dict[int, Decimal]:
    rows = db.execute(select(key, func.sum(ProductionLog.qty)).where(*where).group_by(key))
    return {k: v for k, v in rows}


# route jobs only: rework output is the same metres again, not new production
def _main_logs():
    return ProductionLog.work_order_id.in_(select(WorkOrder.id).where(WorkOrder.roll_id.is_(None)))


# every machine right now: status, job, progress, today's output, crew. One call per refresh.
def board(db: Session, now: datetime | None = None) -> dict:
    now = _now(now)
    machines = sorted(
        db.scalars(select(Machine).where(Machine.active)), key=lambda m: (FLOW[m.type], m.code)
    )
    latest = {
        e.machine_id: e
        for e in db.scalars(
            select(MachineEvent)
            .distinct(MachineEvent.machine_id)
            .order_by(MachineEvent.machine_id, MachineEvent.at.desc(), MachineEvent.id.desc())
        )
    }
    jobs: dict[int, WorkOrder] = {}
    for wo in db.scalars(
        select(WorkOrder)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(
            WorkOrder.status.in_(ACTIVE),
            WorkOrder.machine_id.is_not(None),
            Order.status == OrderStatus.confirmed,
        )
        .order_by(WorkOrder.id)
    ):
        if wo.machine_id not in jobs or wo.status == WorkOrderStatus.running:
            jobs[wo.machine_id] = wo
    job_ids = [wo.id for wo in jobs.values()]
    produced = _sum_by(db, ProductionLog.work_order_id, ProductionLog.work_order_id.in_(job_ids))
    order_codes = dict(
        db.execute(
            select(Order.id, Order.code).where(Order.id.in_({wo.order_id for wo in jobs.values()}))
        ).all()
    )
    today = _sum_by(
        db,
        ProductionLog.machine_id,
        ProductionLog.at >= day_start(now.astimezone(IST).date()),
        _main_logs(),
    )
    queued = dict(
        db.execute(
            select(WorkOrder.machine_id, func.count())
            .join(Order, Order.id == WorkOrder.order_id)
            .where(
                WorkOrder.status == WorkOrderStatus.queued, Order.status == OrderStatus.confirmed
            )
            .group_by(WorkOrder.machine_id)
        ).all()
    )
    try:
        shift_day, shift = current_shift(db, now)
    except NotFound:
        shift_day, shift = None, None
    crew = defaultdict(list)
    if shift:
        for machine_id, name in db.execute(
            select(CrewAssignment.machine_id, Worker.name)
            .join(Worker, Worker.id == CrewAssignment.worker_id)
            .where(
                CrewAssignment.date == shift_day,
                CrewAssignment.shift_id == shift.id,
                or_(CrewAssignment.to_at.is_(None), CrewAssignment.to_at > now),
            )
            .order_by(Worker.name)
        ):
            crew[machine_id].append(name)

    tiles = []
    for m in machines:
        event, wo = latest.get(m.id), jobs.get(m.id)
        tiles.append(
            {
                "machine_id": m.id,
                "code": m.code,
                "name": m.name,
                "type": m.type,
                "unit": m.output_unit,
                "status": event.status if event else MachineStatus.off,
                "since": event.at if event else None,
                "reason": event.reason if event else None,
                "source": event.source if event else None,
                "job": {
                    "work_order_id": wo.id,
                    "code": wo.code,
                    "order_id": wo.order_id,
                    "order_code": order_codes[wo.order_id],
                    "stage": wo.stage,
                    "status": wo.status,
                    "planned": wo.planned_qty,
                    "produced": qty(produced.get(wo.id, 0)),
                    "unit": wo.unit,
                    "roll_id": wo.roll_id,
                }
                if wo
                else None,
                "today_output": qty(today.get(m.id, 0)),
                "queued": queued.get(m.id, 0),
                "crew": crew[m.id],
            }
        )
    return {"as_of": now, "shift_code": shift.code if shift else None, "machines": tiles}


# every job not done yet, with order code and progress: what the queue screen needs in one call
def open_work_orders(db: Session) -> list[dict]:
    rows = db.execute(
        select(WorkOrder, Order.code, Order.deadline)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(WorkOrder.status != WorkOrderStatus.done, Order.status == OrderStatus.confirmed)
        .order_by(WorkOrder.queue_position.nulls_last(), Order.deadline, WorkOrder.seq)
    ).all()
    produced = _sum_by(
        db, ProductionLog.work_order_id, ProductionLog.work_order_id.in_([r[0].id for r in rows])
    )
    return [
        {
            **WorkOrderOut.model_validate(wo).model_dump(),
            "order_code": code,
            "deadline": deadline,
            "produced": qty(produced.get(wo.id, 0)),
        }
        for wo, code, deadline in rows
    ]


# one machine, one IST day: events, seconds per status, output logs
def timeline(db: Session, machine_id: int, day: date, now: datetime | None = None) -> dict:
    machine = db.get(Machine, machine_id)
    if not machine:
        raise NotFound(f"Machine {machine_id} not found")
    start = day_start(day)
    end = min(start + timedelta(days=1), _now(now))
    by_machine = MachineEvent.machine_id == machine.id
    before = db.scalar(
        select(MachineEvent)
        .where(by_machine, MachineEvent.at < start)
        .order_by(MachineEvent.at.desc(), MachineEvent.id.desc())
        .limit(1)
    )
    day_events = db.scalars(
        select(MachineEvent)
        .where(by_machine, MachineEvent.at >= start, MachineEvent.at < start + timedelta(days=1))
        .order_by(MachineEvent.at, MachineEvent.id)
    ).all()
    points = [(e.at, e.status) for e in ([before] if before else []) + list(day_events)]
    # route output only, like the board and month-end: rework redoes metres already counted
    logs = db.scalars(
        select(ProductionLog)
        .where(
            ProductionLog.machine_id == machine.id,
            ProductionLog.at >= start,
            ProductionLog.at < start + timedelta(days=1),
            _main_logs(),
        )
        .order_by(ProductionLog.at)
    ).all()
    made = (log.qty for log in logs)
    return {
        "machine_id": machine.id,
        "code": machine.code,
        "date": day,
        "unit": machine.output_unit,
        "events": day_events,
        "seconds": status_durations(points, start, end) if end > start else {},
        "output": logs,
        "total_output": qty(sum(made, Decimal(0))),
    }


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
    metres = qty(order.qty_m * (1 + PROCESS_ALLOWANCE))
    yarn_kg = yarn_kg_for_fabric(metres, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
    work_orders = []
    for st in fabric.stages:
        unit = STAGE_UNIT[st.stage]
        wo = WorkOrder(
            code=next_code(db, "WO"),
            order_id=order.id,
            stage=st.stage,
            seq=st.seq,
            planned_qty=yarn_kg if unit == Unit.kg else metres,
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


# start the first job in this machine's queue that can run (a dye job with no roll yet waits
# without holding up the one behind it); skip quietly if the machine is stopped or busy
def pull_next(
    db: Session, machine_id: int, user_id: int | None, at: datetime | None = None
) -> WorkOrder | None:
    if machine_status(db, machine_id) not in PULLABLE or _active_jobs(db, machine_id):
        return None
    queue = db.scalars(
        select(WorkOrder.id)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(
            WorkOrder.machine_id == machine_id,
            WorkOrder.status == WorkOrderStatus.queued,
            Order.status == OrderStatus.confirmed,
        )
        .order_by(WorkOrder.queue_position.nulls_last(), WorkOrder.id)
    ).all()
    for wo_id in queue:
        try:
            return _start(db, _lock_work_order(db, wo_id), user_id, at, Source.manual)
        except Conflict:
            continue
    return None


# a waiting job can go on a machine: rework at once, the first stage once its yarn is issued,
# a later stage once the one before it has started; dyeing once weaving is done, so a dye
# range never sits on a job with nothing to dye while other orders' rolls wait
def _ready_to_plan(db: Session, wo: WorkOrder) -> bool:
    if wo.roll_id:
        return True
    earlier = [m for m in _mains(db, wo.order_id) if m.seq < wo.seq]
    if not earlier:
        return bool(_order_issued(db, wo.order_id))
    if wo.stage == Stage.dyeing:
        return earlier[-1].status == WorkOrderStatus.done
    return earlier[-1].status in (*ACTIVE, WorkOrderStatus.done)


# ready waiting jobs go to the least busy working machine of their stage, earliest deadline
# first; with no working machine the job waits and the supervisor decides
def plan_waiting(db: Session, user_id: int | None) -> list[WorkOrder]:
    waiting = db.scalars(
        select(WorkOrder)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(
            WorkOrder.status == WorkOrderStatus.waiting,
            Order.status == OrderStatus.confirmed,
        )
        .order_by(Order.deadline, WorkOrder.id)
    ).all()
    if not waiting:
        return []
    up = [
        m
        for m in db.scalars(select(Machine).where(Machine.active).order_by(Machine.code))
        if machine_status(db, m.id) in PULLABLE
    ]
    load = dict(
        db.execute(
            select(WorkOrder.machine_id, func.count())
            .where(
                WorkOrder.status.in_([WorkOrderStatus.queued, *ACTIVE]),
                WorkOrder.machine_id.is_not(None),
            )
            .group_by(WorkOrder.machine_id)
        ).all()
    )
    planned = []
    for wo in waiting:
        options = [m for m in up if m.type == wo.stage]
        if not options or not _ready_to_plan(db, wo):
            continue
        best = min(options, key=lambda m: (load.get(m.id, 0), m.code))
        wo = _lock_work_order(db, wo.id)
        if wo.status != WorkOrderStatus.waiting:
            continue
        _lock_machine(db, best.id)
        _set_wo_status(db, wo, WorkOrderStatus.queued, user_id, "auto plan")
        wo.machine_id = best.id
        _place_in_queue(db, wo, best.id)
        db.flush()
        load[best.id] = load.get(best.id, 0) + 1
        planned.append(wo)
    return planned


# ready jobs the planner could not place: no running or idle machine of their stage
def unplaced_jobs(db: Session) -> list[WorkOrder]:
    waiting = db.scalars(
        select(WorkOrder)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(WorkOrder.status == WorkOrderStatus.waiting, Order.status == OrderStatus.confirmed)
        .order_by(Order.deadline, WorkOrder.id)
    )
    return [wo for wo in waiting if _ready_to_plan(db, wo)]


# after any floor change: queue what became ready, then start whatever a free machine can take
def advance(db: Session, user_id: int | None, at: datetime | None = None) -> list[WorkOrder]:
    plan_waiting(db, user_id)
    return pull_ready(db, user_id, at)


# every free machine with a queue gets its head started; locked machines are left to their owner
def pull_ready(db: Session, user_id: int | None, at: datetime | None = None) -> list[WorkOrder]:
    busy = select(WorkOrder.machine_id).where(
        WorkOrder.status.in_(ACTIVE), WorkOrder.machine_id.is_not(None)
    )
    ids = (
        select(WorkOrder.machine_id)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(
            WorkOrder.status == WorkOrderStatus.queued,
            Order.status == OrderStatus.confirmed,
            WorkOrder.machine_id.not_in(busy),
        )
    )
    machines = sorted(
        db.scalars(select(Machine).where(Machine.id.in_(ids), Machine.active)),
        key=lambda m: (FLOW[m.type], m.code),
    )
    started = []
    for m in machines:
        lock = select(Machine.id).where(Machine.id == m.id).with_for_update(skip_locked=True)
        mine = db.scalar(lock)
        wo = pull_next(db, m.id, user_id, at) if mine else None
        if wo:
            started.append(wo)
    return started


# order cancelled: its queued jobs go back to waiting; a job already on a machine blocks it
def release_order_jobs(db: Session, order_id: int, user_id: int | None) -> int:
    jobs = db.scalars(
        select(WorkOrder)
        .where(
            WorkOrder.order_id == order_id,
            WorkOrder.status.in_([WorkOrderStatus.queued, *ACTIVE]),
        )
        .order_by(WorkOrder.id)
        .with_for_update()
    ).all()
    started = [j for j in jobs if j.status in ACTIVE]
    if started:
        raise Conflict(
            f"{started[0].code} is {started[0].status} on a machine. Finish it first.",
            code="job_on_machine",
        )
    machines = sorted({j.machine_id for j in jobs})
    for j in jobs:
        _set_wo_status(db, j, WorkOrderStatus.waiting, user_id, "order released")
        j.machine_id = j.queue_position = None
    db.flush()
    for mid in machines:
        pull_next(db, mid, user_id)
    return len(jobs)
