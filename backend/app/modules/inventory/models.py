from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import Source, Unit, str_enum
from app.modules.masters.models import Supplier, YarnItem


class ExpectedDeliveryStatus(StrEnum):
    open = "open"
    partially_received = "partially_received"
    received = "received"
    cancelled = "cancelled"


class ReceiptStatus(StrEnum):
    draft = "draft"
    confirmed = "confirmed"


class BatchStatus(StrEnum):
    pending_identification = "pending_identification"
    inspection = "inspection"
    approved = "approved"
    quarantined = "quarantined"
    rejected = "rejected"


class ItemKind(StrEnum):
    yarn = "yarn"
    fabric = "fabric"


class MoveReason(StrEnum):
    receipt = "receipt"
    approve = "approve"
    quarantine = "quarantine"
    release = "release"
    issue = "issue"
    return_ = "return"
    consume = "consume"
    produce = "produce"
    qc_pass = "qc_pass"
    qc_reject = "qc_reject"
    dispatch = "dispatch"
    adjust = "adjust"


class ReservationStatus(StrEnum):
    active = "active"
    consumed = "consumed"
    released = "released"


# lightweight purchase order: what we expect a supplier to bring
class ExpectedDelivery(Base):
    __tablename__ = "expected_deliveries"
    __table_args__ = (
        CheckConstraint("expected_kg > 0", name="expected_kg_positive"),
        CheckConstraint("rate_paise_per_kg >= 0", name="rate_non_negative"),
    )

    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    yarn_item_id: Mapped[int] = mapped_column(ForeignKey("yarn_items.id"), index=True)
    expected_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    rate_paise_per_kg: Mapped[int] = mapped_column(BigInteger)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    expected_date: Mapped[date] = mapped_column(Date)
    status: Mapped[ExpectedDeliveryStatus] = mapped_column(
        str_enum(ExpectedDeliveryStatus, "expected_delivery_status"),
        default=ExpectedDeliveryStatus.open,
    )

    # read-only, loaded by a second query (selectin) so FOR UPDATE on this table stays legal
    supplier: Mapped[Supplier] = relationship(viewonly=True, lazy="selectin")
    yarn_item: Mapped[YarnItem] = relationship(viewonly=True, lazy="selectin")


# GRN: one truck at the gate. Stock only moves when confirmed.
class Receipt(Base):
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("bill_amount_paise >= 0", name="bill_non_negative"),
        CheckConstraint(
            "status <> 'confirmed' OR confirmed_at IS NOT NULL", name="confirmed_has_time"
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    expected_delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("expected_deliveries.id"), index=True
    )
    vehicle_no: Mapped[str | None] = mapped_column(String(20))
    bill_no: Mapped[str | None] = mapped_column(String(40))
    bill_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[ReceiptStatus] = mapped_column(
        str_enum(ReceiptStatus, "receipt_status"), default=ReceiptStatus.draft
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier] = relationship(viewonly=True, lazy="selectin")


# one supplier lot inside one receipt; missing label -> pending_identification, item unknown
class YarnBatch(Base):
    __tablename__ = "yarn_batches"
    __table_args__ = (
        UniqueConstraint("supplier_id", "supplier_lot", "receipt_id"),
        CheckConstraint("received_kg > 0", name="received_kg_positive"),
        CheckConstraint("unit_cost_paise_per_kg >= 0", name="unit_cost_non_negative"),
        CheckConstraint(
            "status = 'pending_identification' OR yarn_item_id IS NOT NULL",
            name="identified_has_item",
        ),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    yarn_item_id: Mapped[int | None] = mapped_column(ForeignKey("yarn_items.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    supplier_lot: Mapped[str | None] = mapped_column(String(60))
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"), index=True)
    received_kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_cost_paise_per_kg: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[BatchStatus] = mapped_column(
        str_enum(BatchStatus, "batch_status"), default=BatchStatus.inspection
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    mismatch_notes: Mapped[str | None] = mapped_column(Text)

    yarn_item: Mapped[YarnItem | None] = relationship(viewonly=True, lazy="selectin")
    supplier: Mapped[Supplier] = relationship(viewonly=True, lazy="selectin")
    receipt: Mapped[Receipt] = relationship(viewonly=True, lazy="selectin")


# append-only ledger. Stock at a location = moves in - moves out. Never updated, never deleted.
class StockMove(Base):
    __tablename__ = "stock_moves"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("from_location_id <> to_location_id", name="moves_somewhere"),
        CheckConstraint(
            "(item_kind = 'yarn' AND yarn_batch_id IS NOT NULL AND roll_id IS NULL AND unit = 'kg')"
            " OR (item_kind = 'fabric' AND roll_id IS NOT NULL AND yarn_batch_id IS NULL"
            " AND unit = 'm')",
            name="item_matches_kind",
        ),
        Index("ix_stock_moves_batch_to", "yarn_batch_id", "to_location_id"),
        Index("ix_stock_moves_batch_from", "yarn_batch_id", "from_location_id"),
        Index("ix_stock_moves_roll_to", "roll_id", "to_location_id"),
        Index("ix_stock_moves_roll_from", "roll_id", "from_location_id"),
        Index("ix_stock_moves_ref", "ref_type", "ref_id"),
    )

    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    item_kind: Mapped[ItemKind] = mapped_column(str_enum(ItemKind, "item_kind"))
    yarn_batch_id: Mapped[int | None] = mapped_column(ForeignKey("yarn_batches.id"))
    roll_id: Mapped[int | None] = mapped_column(ForeignKey("rolls.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit: Mapped[Unit] = mapped_column(str_enum(Unit, "unit"))
    from_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    to_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    reason: Mapped[MoveReason] = mapped_column(str_enum(MoveReason, "move_reason"))
    ref_type: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[Source] = mapped_column(str_enum(Source, "source"), default=Source.manual)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (CheckConstraint("kg > 0", name="kg_positive"),)

    yarn_batch_id: Mapped[int] = mapped_column(ForeignKey("yarn_batches.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    kg: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    status: Mapped[ReservationStatus] = mapped_column(
        str_enum(ReservationStatus, "reservation_status"), default=ReservationStatus.active
    )
