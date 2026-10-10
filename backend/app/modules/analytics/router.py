from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.analytics import service
from app.modules.analytics.models import InsightStatus
from app.modules.analytics.schemas import InsightOut
from app.modules.auth.models import Role

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_roles(Role.supervisor))]
)


@router.get("/insights", response_model=Paged[InsightOut])
def list_insights(
    page: PageDep, status: InsightStatus | None = None, db: Session = Depends(get_db)
):
    return service.list_insights(db, page, status)
