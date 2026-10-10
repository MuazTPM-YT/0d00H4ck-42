from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.workforce import service
from app.modules.workforce.schemas import (
    AttendanceIn,
    AttendanceOut,
    CarryIn,
    CarryOut,
    CrewIn,
    CrewOut,
    CurrentShiftOut,
)

router = APIRouter(
    prefix="/workforce",
    tags=["workforce"],
    dependencies=[Depends(require_roles(Role.supervisor, Role.accounts))],
)
Supervisor = Depends(require_roles(Role.supervisor))


@router.get("/attendance", response_model=Paged[AttendanceOut])
def list_attendance(
    page: PageDep,
    date: date | None = None,
    shift_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_attendance(db, page, date, shift_id)


@router.put("/attendance", response_model=AttendanceOut)
def set_attendance(body: AttendanceIn, db: Session = Depends(get_db), user: User = Supervisor):
    return service.set_attendance(db, body, user.id)


@router.get("/current-shift", response_model=CurrentShiftOut)
def current_shift(db: Session = Depends(get_db)):
    day, shift = service.current_shift(db, datetime.now(UTC))
    return {"date": day, "shift_id": shift.id, "shift_code": shift.code}


@router.get("/crew", response_model=list[CrewOut])
def list_crew(date: date, shift_id: int, db: Session = Depends(get_db)):
    return service.list_crew(db, date, shift_id)


@router.post("/crew", response_model=CrewOut, status_code=201)
def assign_crew(body: CrewIn, db: Session = Depends(get_db), user: User = Supervisor):
    row = service.assign_crew(db, body, user.id)
    return next(c for c in service.list_crew(db, row.date, row.shift_id) if c["id"] == row.id)


@router.post("/crew/carry", response_model=CarryOut)
def carry_crew(body: CarryIn, db: Session = Depends(get_db), user: User = Supervisor):
    return {"created": service.carry_crew(db, body, user.id)}


@router.post("/crew/{assignment_id}/end", response_model=CrewOut)
def end_crew(assignment_id: int, db: Session = Depends(get_db), user: User = Supervisor):
    row = service.end_crew(db, assignment_id, user.id)
    return next(c for c in service.list_crew(db, row.date, row.shift_id) if c["id"] == row.id)
