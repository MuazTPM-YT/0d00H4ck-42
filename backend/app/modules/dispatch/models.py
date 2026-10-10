import secrets
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class DispatchStatus(StrEnum):
    draft = "draft"
    loading = "loading"
    confirmed = "confirmed"


def new_delivery_token() -> str:
    return secrets.token_urlsafe(24)


# delivery is a fact on top of confirmed: shipped metres, invoice and order close stay as they are
class Dispatch(Base):
    __tablename__ = "dispatches"
    __table_args__ = (
        CheckConstraint(
            "status <> 'confirmed' OR (confirmed_at IS NOT NULL AND vehicle_no IS NOT NULL)",
            name="confirmed_has_vehicle_and_time",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR (status = 'confirmed' AND received_by IS NOT NULL)",
            name="delivered_after_it_left",
        ),
        CheckConstraint("otp_tries >= 0", name="otp_tries_not_negative"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    driver: Mapped[str | None] = mapped_column(String(80))
    driver_email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[DispatchStatus] = mapped_column(
        str_enum(DispatchStatus, "dispatch_status"), default=DispatchStatus.draft
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # driver link key; the page only opens once the truck is confirmed
    delivery_token: Mapped[str] = mapped_column(String(64), unique=True, default=new_delivery_token)
    # set at confirm, shown on the buyer link only; the buyer hands it over on receipt
    delivery_otp: Mapped[str | None] = mapped_column(String(6))
    otp_tries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_by: Mapped[str | None] = mapped_column(String(80))
    delivery_note: Mapped[str | None] = mapped_column(String(500))


# UNIQUE roll_id: a roll can sit on one dispatch only, ever (R18)
class DispatchRoll(Base):
    __tablename__ = "dispatch_rolls"

    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), index=True)
    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"), unique=True)
