from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.quality import service
from app.modules.quality.models import RollStatus
from app.modules.quality.schemas import (
    QcCheckIn,
    QcResultOut,
    QualitySummaryOut,
    RollDetailOut,
    RollOut,
    RollRowOut,
)

router = APIRouter(prefix="/quality", tags=["quality"], dependencies=[Depends(get_current_user)])
Inspector = Depends(require_roles(Role.qc))


@router.get("/rolls", response_model=Paged[RollOut])
def list_rolls(
    page: PageDep,
    status: RollStatus | None = None,
    order_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_rolls(db, page, status, order_id)


@router.get("/queue", response_model=Paged[RollRowOut])
def queue(page: PageDep, db: Session = Depends(get_db)):
    return service.queue(db, page)


@router.get("/summary", response_model=QualitySummaryOut)
def summary(days: Annotated[int, Query(ge=1, le=365)] = 30, db: Session = Depends(get_db)):
    return service.summary(db, days)


@router.get("/rolls/{roll_id}", response_model=RollDetailOut)
def roll_detail(roll_id: int, db: Session = Depends(get_db)):
    return service.roll_detail(db, roll_id)


@router.post("/rolls/{roll_id}/checks", response_model=QcResultOut, status_code=201)
def decide(roll_id: int, body: QcCheckIn, db: Session = Depends(get_db), user: User = Inspector):
    return service.decide(db, roll_id, body, user.id)
