from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.codes import next_code
from app.core.enums import Stage, Unit
from app.core.errors import NotFound
from app.core.pagination import Page, paginate
from app.core.units import yarn_kg_for_fabric
from app.modules.masters.models import FabricType
from app.modules.orders.models import Order
from app.modules.production.models import MachineStatus, WorkOrder, WorkOrderStatus

WORK_ORDER_TRANSITIONS = {
    WorkOrderStatus.waiting: {WorkOrderStatus.queued},
    WorkOrderStatus.queued: {WorkOrderStatus.running, WorkOrderStatus.waiting},
    WorkOrderStatus.running: {WorkOrderStatus.paused, WorkOrderStatus.done},
    WorkOrderStatus.paused: {WorkOrderStatus.running},
}
# machine status is a reported fact: any change is allowed, repeating the current one is not
MACHINE_TRANSITIONS = {s: set(MachineStatus) - {s} for s in MachineStatus}
STAGE_UNIT = {Stage.spinning: Unit.kg, Stage.weaving: Unit.m, Stage.dyeing: Unit.m}


def list_work_orders(
    db: Session, page: Page, status: WorkOrderStatus | None = None, order_id: int | None = None
) -> dict:
    stmt = select(WorkOrder).order_by(WorkOrder.order_id.desc(), WorkOrder.seq)
    if status:
        stmt = stmt.where(WorkOrder.status == status)
    if order_id:
        stmt = stmt.where(WorkOrder.order_id == order_id)
    return paginate(db, stmt, page)


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
    raise NotImplementedError("production.machine_status")


# per stage: planned, produced so far, unit
def order_progress(db: Session, order_id: int) -> dict[Stage, dict]:
    raise NotImplementedError("production.order_progress")


# new work order for one roll sent back by QC; roll_id set, seq after the original stage
def create_rework_work_order(db: Session, roll_id: int, stage: Stage, user_id: int) -> WorkOrder:
    raise NotImplementedError("production.create_rework_work_order")
