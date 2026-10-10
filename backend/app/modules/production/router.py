from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.pagination import Paged, PageDep
from app.modules.production import service
from app.modules.production.models import WorkOrderStatus
from app.modules.production.schemas import WorkOrderOut

router = APIRouter(
    prefix="/production", tags=["production"], dependencies=[Depends(get_current_user)]
)


@router.get("/work-orders", response_model=Paged[WorkOrderOut])
def list_work_orders(
    page: PageDep,
    status: WorkOrderStatus | None = None,
    order_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_work_orders(db, page, status, order_id)
