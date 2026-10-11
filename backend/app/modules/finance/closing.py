from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.dates import mill_today
from app.core.errors import Conflict, NotFound, Unprocessable
from app.modules.auth.models import User
from app.modules.finance.models import MonthClose


def _first(month: str) -> date:
    return date.fromisoformat(f"{month}-01")


def closed_months(db: Session) -> list[str]:
    return [f"{m:%Y-%m}" for m in db.scalars(select(MonthClose.month).order_by(MonthClose.month))]


# every write dated inside a closed month goes through here first
def ensure_open(db: Session, day: date, field: str = "date") -> None:
    ensure_range_open(db, day, day, field)


def ensure_range_open(db: Session, start: date, end: date, field: str) -> None:
    hit = db.scalar(
        select(MonthClose.month)
        .where(MonthClose.month >= start.replace(day=1), MonthClose.month <= end)
        .limit(1)
    )
    if hit:
        raise Conflict(
            f"{hit:%B %Y} is closed. The owner reopens it to change anything dated in it.",
            field=field,
            code="month_closed",
        )


# only a month that has ended can close: today's dispatches and invoices always land in an open one
def close_month(db: Session, user: User, month: str) -> list[str]:
    first = _first(month)
    if first >= mill_today().replace(day=1):
        raise Unprocessable("Only a month that has ended can be closed", field="month")
    if db.scalar(select(MonthClose.id).where(MonthClose.month == first)):
        raise Conflict(f"{first:%B %Y} is already closed", field="month")
    row = MonthClose(month=first, closed_by=user.id)
    db.add(row)
    db.flush()
    audit.record(db, user.id, "close", "month_closes", row.id, data={"month": month})
    db.commit()
    return closed_months(db)


def reopen_month(db: Session, user: User, month: str, reason: str) -> list[str]:
    row = db.scalar(select(MonthClose).where(MonthClose.month == _first(month)))
    if not row:
        raise NotFound(f"{month} is not closed", field="month")
    audit.record(
        db, user.id, "reopen", "month_closes", row.id, reason=reason, data={"month": month}
    )
    db.delete(row)
    db.commit()
    return closed_months(db)
