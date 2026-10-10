from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.inventory import service as inventory
from app.modules.inventory.schemas import ReasonIn
from app.modules.orders import service
from app.modules.orders.models import OrderStatus
from app.modules.orders.schemas import (
    AllocationOut,
    CloseIn,
    OrderIn,
    OrderOut,
    RequirementIn,
    ToBuyRow,
    YarnLine,
)

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])

Sales = Depends(require_roles(Role.accounts))


@router.get("", response_model=Paged[OrderOut])
def list_orders(
    page: PageDep,
    status: OrderStatus | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    db: Session = Depends(get_db),
):
    return service.list_orders(db, page, status, q)


@router.post("", response_model=OrderOut, status_code=201)
def create_order(data: OrderIn, db: Session = Depends(get_db), user: User = Sales):
    return service.create_order(db, user, data)


@router.post("/requirement-preview", response_model=list[YarnLine])
def requirement_preview(data: RequirementIn, db: Session = Depends(get_db)):
    return service.requirement_preview(db, data)


# R4 buying list: shortfall of confirmed orders minus yarn already on order
@router.get(
    "/to-buy",
    response_model=list[ToBuyRow],
    dependencies=[Depends(require_roles(Role.accounts, Role.store))],
)
def to_buy(db: Session = Depends(get_db)):
    return inventory.to_buy(db)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return service.get_order(db, order_id)


@router.get("/{order_id}/yarn-requirement", response_model=list[YarnLine])
def yarn_requirement(order_id: int, db: Session = Depends(get_db)):
    return service.yarn_requirement(db, order_id)


@router.get("/{order_id}/allocation", response_model=AllocationOut)
def allocation(order_id: int, db: Session = Depends(get_db)):
    return inventory.order_allocation(db, order_id)


@router.post("/{order_id}/confirm", response_model=AllocationOut)
def confirm(order_id: int, db: Session = Depends(get_db), user: User = Sales):
    return service.confirm_order(db, user, order_id)


@router.post("/{order_id}/reserve", response_model=AllocationOut)
def reserve(order_id: int, db: Session = Depends(get_db), user: User = Sales):
    return service.reserve_again(db, user, order_id)


# accounts ends an order by hand; short of the ordered metres needs a reason
@router.post("/{order_id}/close", response_model=OrderOut)
def close(order_id: int, data: CloseIn, db: Session = Depends(get_db), user: User = Sales):
    return service.close(db, user, order_id, data.reason)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel(order_id: int, data: ReasonIn, db: Session = Depends(get_db), user: User = Sales):
    return service.cancel_order(db, user, order_id, data.reason)
