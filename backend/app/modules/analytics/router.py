from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.analytics import service
from app.modules.analytics.models import InsightStatus, Severity
from app.modules.analytics.schemas import (
    DeliveryEstimateOut,
    InsightOut,
    NoteIn,
    RunOut,
)
from app.modules.auth.models import Role, User

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user)]
)
# who promises dates to buyers, and who plans the floor that keeps them
Planners = Depends(require_roles(Role.sales, Role.supervisor))


# every role sees the kinds of finding it acts on (owner sees all)
@router.get("/insights", response_model=Paged[InsightOut])
def list_insights(
    page: PageDep,
    status: InsightStatus | None = None,
    severity: Severity | None = None,
    kind: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.list_insights(db, page, user.role, status, severity, kind)


@router.get("/insights/{insight_id}", response_model=InsightOut)
def get_insight(
    insight_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return service.get_insight(db, insight_id, user.role)


@router.post("/insights/{insight_id}/acknowledge", response_model=InsightOut)
def acknowledge(
    insight_id: int,
    body: NoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.set_insight_status(db, insight_id, InsightStatus.acknowledged, body.note, user)


@router.post("/insights/{insight_id}/resolve", response_model=InsightOut)
def resolve(
    insight_id: int,
    body: NoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.set_insight_status(db, insight_id, InsightStatus.resolved, body.note, user)


@router.post("/run", response_model=RunOut, dependencies=[Depends(require_roles(Role.supervisor))])
def run_detectors(db: Session = Depends(get_db)):
    return service.run_detectors(db)


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
