import datetime as dt
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class AttendanceStatus(StrEnum):
    present = "present"
    absent = "absent"
    half_day = "half_day"


class AttendanceSource(StrEnum):
    crew = "crew"
    manual = "manual"


# who ran which machine in which shift; to_at open while still on the machine
class CrewAssignment(Base):
    __tablename__ = "crew_assignments"
    __table_args__ = (CheckConstraint("to_at IS NULL OR to_at > from_at", name="to_after_from"),)

    date: Mapped[dt.date] = mapped_column(Date, index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    to_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# filled from crew assignments; manual only for corrections. Wages read this.
class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("date", "shift_id", "worker_id"),)

    date: Mapped[dt.date] = mapped_column(Date)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        str_enum(AttendanceStatus, "attendance_status")
    )
    source: Mapped[AttendanceSource] = mapped_column(
        str_enum(AttendanceSource, "attendance_source"), default=AttendanceSource.crew
    )
