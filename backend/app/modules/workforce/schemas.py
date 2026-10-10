from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.errors import FieldError
from app.core.types import Note
from app.modules.workforce.models import AttendanceSource, AttendanceStatus

Id = Annotated[int, Field(gt=0)]
# shift times are mill clock times; IST has no daylight saving, so a fixed offset is exact
IST = timezone(timedelta(hours=5, minutes=30))


def _not_future(value: date) -> date:
    today = datetime.now(UTC).astimezone(IST).date()
    if value > today:
        raise FieldError("date", "Date cannot be in the future")
    return value


PastDate = Annotated[date, AfterValidator(_not_future)]


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    shift_id: int
    worker_id: int
    status: AttendanceStatus
    source: AttendanceSource


class AttendanceIn(BaseModel):
    date: PastDate
    shift_id: Id
    worker_id: Id
    status: AttendanceStatus
    reason: Note


class CrewIn(BaseModel):
    date: PastDate
    shift_id: Id
    worker_id: Id
    machine_id: Id


class CrewOut(BaseModel):
    id: int
    date: date
    shift_id: int
    worker_id: int
    worker_code: str
    worker_name: str
    machine_id: int
    machine_code: str
    from_at: datetime
    to_at: datetime | None


class CurrentShiftOut(BaseModel):
    date: date
    shift_id: int
    shift_code: str
