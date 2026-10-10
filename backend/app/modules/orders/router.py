from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.pagination import Paged, PageDep
from app.modules.orders import service
from app.modules.orders.models import OrderStatus
from app.modules.orders.schemas import OrderOut, YarnLine

router = APIRouter(prefix="/orders", tags=["orders"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=Paged[OrderOut])
def list_orders(page: PageDep, status: OrderStatus | None = None, db: Session = Depends(get_db)):
    return service.list_orders(db, page, status)


@router.get("/{order_id}/yarn-requirement", response_model=list[YarnLine])
def yarn_requirement(order_id: int, db: Session = Depends(get_db)):
    return service.yarn_requirement(db, order_id)
