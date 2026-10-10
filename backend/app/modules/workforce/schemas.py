from datetime import date

from pydantic import BaseModel, ConfigDict

from app.modules.workforce.models import AttendanceSource, AttendanceStatus


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    shift_id: int
    worker_id: int
    status: AttendanceStatus
    source: AttendanceSource
