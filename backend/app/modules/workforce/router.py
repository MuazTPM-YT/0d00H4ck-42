from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role
from app.modules.workforce import service
from app.modules.workforce.schemas import AttendanceOut

router = APIRouter(
    prefix="/workforce",
    tags=["workforce"],
    dependencies=[Depends(require_roles(Role.supervisor, Role.accounts))],
)


@router.get("/attendance", response_model=Paged[AttendanceOut])
def list_attendance(page: PageDep, date: date | None = None, db: Session = Depends(get_db)):
    return service.list_attendance(db, page, date)
