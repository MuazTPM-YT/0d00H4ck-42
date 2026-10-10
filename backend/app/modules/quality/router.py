from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.quality import service
from app.modules.quality.models import QcDecision, RollStatus
from app.modules.quality.schemas import (
    CheckOut,
    InspectIn,
    InspectOut,
    QueueRow,
    RollCode,
    RollOut,
    SummaryOut,
    TraceOut,
)

router = APIRouter(prefix="/quality", tags=["quality"], dependencies=[Depends(get_current_user)])
Inspector = Depends(require_roles(Role.qc))


@router.get("/rolls", response_model=Paged[RollOut])
def list_rolls(
    page: PageDep,
    status: RollStatus | None = None,
    order_id: int | None = None,
    code: RollCode | None = None,
    db: Session = Depends(get_db),
):
    return service.list_rolls(db, page, status, order_id, code)


# roll genealogy: anyone who handles the roll can trace it back to its yarn
@router.get("/rolls/{roll_id}", response_model=TraceOut)
def roll_trace(roll_id: int, db: Session = Depends(get_db)):
    return service.roll_trace(db, roll_id)


@router.post("/rolls/{roll_id}/inspect", response_model=InspectOut)
def inspect(roll_id: int, body: InspectIn, db: Session = Depends(get_db), user: User = Inspector):
    return service.inspect(db, roll_id, body, user)


@router.get("/queue", response_model=Paged[QueueRow])
def queue(page: PageDep, db: Session = Depends(get_db)):
    return service.queue(db, page)


@router.get("/checks", response_model=Paged[CheckOut])
def list_checks(
    page: PageDep,
    decision: QcDecision | None = None,
    order_id: int | None = None,
    machine_id: int | None = None,
    roll_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_checks(db, page, decision, order_id, machine_id, roll_id)


@router.get("/summary", response_model=SummaryOut)
def summary(days: Annotated[int, Query(ge=1, le=365)] = 30, db: Session = Depends(get_db)):
    return service.summary(db, days)
