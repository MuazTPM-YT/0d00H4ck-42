import secrets
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import str_enum
from app.modules.masters.models import Buyer, FabricType


class OrderStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"
    cancelled = "cancelled"
    closed = "closed"


def new_tracking_token() -> str:
    return secrets.token_urlsafe(24)


# buyer-facing stage (in production, QC, ready, dispatched) is derived, never stored here
class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("qty_m > 0", name="qty_positive"),
        CheckConstraint("rate_paise_per_m >= 0", name="rate_non_negative"),
        CheckConstraint(
            "status = 'draft' OR status = 'cancelled' OR confirmed_at IS NOT NULL",
            name="confirmed_has_time",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    fabric_type_id: Mapped[int] = mapped_column(ForeignKey("fabric_types.id"), index=True)
    colour: Mapped[str] = mapped_column(String(40))
    qty_m: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    rate_paise_per_m: Mapped[int] = mapped_column(BigInteger)
    deadline: Mapped[date] = mapped_column(Date)
    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, "order_status"), default=OrderStatus.draft
    )
    tracking_token: Mapped[str] = mapped_column(String(64), unique=True, default=new_tracking_token)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # read-only joins for display; no schema change
    buyer: Mapped[Buyer] = relationship(viewonly=True, lazy="joined")
    fabric_type: Mapped[FabricType] = relationship(viewonly=True, lazy="joined")
