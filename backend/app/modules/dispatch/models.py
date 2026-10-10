from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class DispatchStatus(StrEnum):
    draft = "draft"
    loading = "loading"
    confirmed = "confirmed"


class Dispatch(Base):
    __tablename__ = "dispatches"
    __table_args__ = (
        CheckConstraint(
            "status <> 'confirmed' OR (confirmed_at IS NOT NULL AND vehicle_no IS NOT NULL)",
            name="confirmed_has_vehicle_and_time",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    driver: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[DispatchStatus] = mapped_column(
        str_enum(DispatchStatus, "dispatch_status"), default=DispatchStatus.draft
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# UNIQUE roll_id: a roll can sit on one dispatch only, ever (R18)
class DispatchRoll(Base):
    __tablename__ = "dispatch_rolls"

    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), index=True)
    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"), unique=True)
