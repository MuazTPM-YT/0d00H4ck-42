from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.analytics import service
from app.modules.analytics.models import InsightStatus
from app.modules.analytics.schemas import DeliveryEstimateOut, InsightOut
from app.modules.auth.models import Role

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user)]
)
# who promises dates to buyers, and who plans the floor that keeps them
Planners = Depends(require_roles(Role.sales, Role.supervisor))


@router.get(
    "/insights",
    response_model=Paged[InsightOut],
    dependencies=[Depends(require_roles(Role.supervisor))],
)
def list_insights(
    page: PageDep, status: InsightStatus | None = None, db: Session = Depends(get_db)
):
    return service.list_insights(db, page, status)


@router.get("/delivery", response_model=list[DeliveryEstimateOut], dependencies=[Planners])
def delivery_board(db: Session = Depends(get_db)):
    return service.delivery_board(db)


@router.get(
    "/orders/{order_id}/delivery-estimate",
    response_model=DeliveryEstimateOut,
    dependencies=[Planners],
)
def delivery_estimate(order_id: int, db: Session = Depends(get_db)):
    return service.delivery_estimate(db, order_id)
