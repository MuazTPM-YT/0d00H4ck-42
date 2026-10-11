from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.production import service
from app.modules.production.models import WorkOrderStatus
from app.modules.production.schemas import (
    BoardOut,
    MachineEventIn,
    MachineEventOut,
    MoveIn,
    OpenWorkOrderOut,
    OutputIn,
    ProcessWaitingIn,
    ProcessWaitingOut,
    ProductionLogOut,
    QueueIn,
    ReorderIn,
    RollIn,
    RollOut,
    RollProcessIn,
    TimelineOut,
    WorkOrderOut,
)

router = APIRouter(
    prefix="/production", tags=["production"], dependencies=[Depends(get_current_user)]
)
# machine feeds and scanners log in as a supervisor account
Supervisor = Depends(require_roles(Role.supervisor))


@router.get("/work-orders", response_model=Paged[WorkOrderOut])
def list_work_orders(
    page: PageDep,
    status: WorkOrderStatus | None = None,
    order_id: int | None = None,
    machine_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_work_orders(db, page, status, order_id, machine_id)


@router.get("/work-orders/open", response_model=list[OpenWorkOrderOut])
def open_work_orders(db: Session = Depends(get_db)):
    return service.open_work_orders(db)


@router.post("/work-orders/{work_order_id}/queue", response_model=WorkOrderOut)
def queue(
    work_order_id: int, body: QueueIn, db: Session = Depends(get_db), user: User = Supervisor
):
    return service.queue_work_order(db, work_order_id, body.machine_id, user.id)


@router.post("/work-orders/{work_order_id}/unqueue", response_model=WorkOrderOut)
def unqueue(work_order_id: int, db: Session = Depends(get_db), user: User = Supervisor):
    return service.unqueue_work_order(db, work_order_id, user.id)


@router.post("/work-orders/{work_order_id}/start", response_model=WorkOrderOut)
def start(work_order_id: int, db: Session = Depends(get_db), user: User = Supervisor):
    return service.start_work_order(db, work_order_id, user.id)


@router.post("/work-orders/{work_order_id}/move", response_model=WorkOrderOut)
def move(work_order_id: int, body: MoveIn, db: Session = Depends(get_db), user: User = Supervisor):
    return service.move_work_order(db, work_order_id, body.machine_id, body.reason, user.id)


@router.post("/work-orders/{work_order_id}/finish", response_model=WorkOrderOut)
def finish(work_order_id: int, db: Session = Depends(get_db), user: User = Supervisor):
    return service.finish_work_order(db, work_order_id, user.id)


@router.post("/work-orders/{work_order_id}/process-waiting", response_model=ProcessWaitingOut)
def process_waiting(
    work_order_id: int,
    body: ProcessWaitingIn | None = None,
    db: Session = Depends(get_db),
    user: User = Supervisor,
):
    return service.process_waiting(db, work_order_id, body or ProcessWaitingIn(), user.id)


@router.put("/machines/{machine_id}/queue", response_model=list[WorkOrderOut])
def reorder(
    machine_id: int, body: ReorderIn, db: Session = Depends(get_db), user: User = Supervisor
):
    return service.reorder_queue(db, machine_id, body.work_order_ids, user.id)


@router.post("/machine-events", response_model=MachineEventOut, status_code=201)
def machine_event(body: MachineEventIn, db: Session = Depends(get_db), user: User = Supervisor):
    return service.report_machine_event(db, body, user.id)


@router.post("/output", response_model=ProductionLogOut, status_code=201)
def output(body: OutputIn, db: Session = Depends(get_db), user: User = Supervisor):
    return service.log_output(db, body, user.id)


@router.post("/rolls", response_model=RollOut, status_code=201)
def cut_roll(body: RollIn, db: Session = Depends(get_db), user: User = Supervisor):
    return service.cut_roll(db, body, user.id)


@router.post("/rolls/{roll_id}/process", response_model=RollOut)
def process_roll(
    roll_id: int, body: RollProcessIn, db: Session = Depends(get_db), user: User = Supervisor
):
    return service.process_roll(db, roll_id, body, user.id)


@router.get("/board", response_model=BoardOut)
def board(db: Session = Depends(get_db)):
    return service.board(db)


@router.get("/machines/{machine_id}/timeline", response_model=TimelineOut)
def timeline(machine_id: int, date: date, db: Session = Depends(get_db)):
    return service.timeline(db, machine_id, date)
