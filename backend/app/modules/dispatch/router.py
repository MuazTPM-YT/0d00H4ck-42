from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.dispatch import service
from app.modules.dispatch.models import DispatchStatus
from app.modules.dispatch.schemas import (
    CornerItem,
    DeliverIn,
    DeliveryOut,
    DispatchCreate,
    DispatchDetail,
    DispatchOut,
    DispatchRow,
    DriverEmailIn,
    OverrideIn,
    ScanIn,
    ScanResult,
    ShelfGroup,
    VehicleIn,
)

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# accounts and supervisor read; only the dispatch clerk loads trucks
Readers = Depends(require_roles(Role.dispatch, Role.accounts, Role.supervisor))
Clerk = Depends(require_roles(Role.dispatch))
Supervisor = Depends(require_roles(Role.supervisor))


@router.get("/dispatches", response_model=Paged[DispatchRow], dependencies=[Readers])
def list_dispatches(
    page: PageDep,
    status: DispatchStatus | None = None,
    order_id: int | None = None,
    buyer_id: int | None = None,
    vehicle: Annotated[str | None, Query(max_length=20)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    return service.list_dispatches(
        db, page, status, order_id, buyer_id, vehicle, date_from, date_to
    )


@router.post("/dispatches", response_model=DispatchOut, status_code=201)
def create_dispatch(data: DispatchCreate, db: Session = Depends(get_db), user: User = Clerk):
    return service.create_dispatch(
        db, user, data.order_id, data.vehicle_no, data.driver, data.driver_email
    )


@router.get("/dispatches/{dispatch_id}", response_model=DispatchDetail, dependencies=[Readers])
def get_dispatch(dispatch_id: int, db: Session = Depends(get_db)):
    return service.get_detail(db, dispatch_id)


@router.put("/dispatches/{dispatch_id}/vehicle", response_model=DispatchDetail)
def set_vehicle(
    dispatch_id: int, data: VehicleIn, db: Session = Depends(get_db), user: User = Clerk
):
    return service.set_vehicle(
        db, user, dispatch_id, data.vehicle_no, data.driver, data.driver_email
    )


@router.post("/dispatches/{dispatch_id}/scan", response_model=ScanResult)
def scan(dispatch_id: int, data: ScanIn, db: Session = Depends(get_db), user: User = Clerk):
    return service.scan(db, user, dispatch_id, data.roll_code, data.idempotency_key)


@router.delete("/dispatches/{dispatch_id}/rolls/{roll_id}", response_model=DispatchDetail)
def unload(dispatch_id: int, roll_id: int, db: Session = Depends(get_db), user: User = Clerk):
    return service.unload(db, user, dispatch_id, roll_id)


@router.post("/dispatches/{dispatch_id}/shade-override", response_model=DispatchDetail)
def shade_override(
    dispatch_id: int, data: OverrideIn, db: Session = Depends(get_db), user: User = Supervisor
):
    return service.shade_override(db, user, dispatch_id, data.reason)


@router.post("/dispatches/{dispatch_id}/confirm", response_model=DispatchDetail)
def confirm(
    dispatch_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Clerk,
):
    out = service.confirm(db, user, dispatch_id)
    # driver gets their link by email once the response has gone
    background.add_task(service.email_driver_later, dispatch_id, user.id)
    return out


# office path for a driver with no signal: same code check, same try limit
@router.post("/dispatches/{dispatch_id}/deliver", response_model=DispatchDetail)
def office_deliver(
    dispatch_id: int, data: DeliverIn, db: Session = Depends(get_db), user: User = Clerk
):
    return service.office_deliver(db, user, dispatch_id, data.model_dump())


@router.post("/dispatches/{dispatch_id}/new-code", response_model=DispatchDetail)
def new_code(dispatch_id: int, db: Session = Depends(get_db), user: User = Clerk):
    return service.new_code(db, user, dispatch_id)


@router.post("/dispatches/{dispatch_id}/email-driver", response_model=DispatchDetail)
def email_driver(
    dispatch_id: int, data: DriverEmailIn, db: Session = Depends(get_db), user: User = Clerk
):
    return service.resend_driver(db, user, dispatch_id, data.driver_email)


@router.get("/finished-stock", response_model=list[ShelfGroup], dependencies=[Readers])
def finished_stock(db: Session = Depends(get_db)):
    return service.shelf(db)


@router.get("/corner-check", response_model=list[CornerItem], dependencies=[Readers])
def corner_check(
    days: Annotated[int, Query(ge=1, le=365)] = service.SHELF_DAYS, db: Session = Depends(get_db)
):
    return service.corner_check(db, days)


# public, no login: the token opens one truck that has left, the buyer's code closes it
delivery = APIRouter(prefix="/deliver", tags=["delivery"])
Token = Path(min_length=10, max_length=64)


@delivery.get("/{token}", response_model=DeliveryOut)
def delivery_view(token: str = Token, db: Session = Depends(get_db)):
    return service.delivery_view(db, token)


@delivery.post("/{token}", response_model=DeliveryOut)
def deliver(data: DeliverIn, token: str = Token, db: Session = Depends(get_db)):
    return service.deliver(db, token, data.model_dump())
