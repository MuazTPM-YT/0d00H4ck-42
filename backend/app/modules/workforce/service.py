from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import Page, paginate
from app.modules.workforce.models import Attendance


def list_attendance(db: Session, page: Page, on: date | None = None) -> dict:
    stmt = select(Attendance).order_by(
        Attendance.date.desc(), Attendance.shift_id, Attendance.worker_id
    )
    if on:
        stmt = stmt.where(Attendance.date == on)
    return paginate(db, stmt, page)
