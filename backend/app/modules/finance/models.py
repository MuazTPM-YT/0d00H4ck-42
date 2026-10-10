import datetime as dt
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import str_enum


class InvoiceStatus(StrEnum):
    issued = "issued"
    part_paid = "part_paid"
    paid = "paid"


class PaymentMode(StrEnum):
    bank_transfer = "bank_transfer"
    upi = "upi"
    cheque = "cheque"
    cash = "cash"


class WageRunStatus(StrEnum):
    draft = "draft"
    final = "final"
    paid = "paid"


class ExpenseCategory(StrEnum):
    power = "power"
    maintenance = "maintenance"
    transport = "transport"
    rent = "rent"
    other = "other"


# one invoice per dispatch; lines copied from dispatched rolls, never typed
class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("subtotal_paise >= 0 AND tax_paise >= 0", name="amounts_non_negative"),
        CheckConstraint("total_paise = subtotal_paise + tax_paise", name="total_adds_up"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("dispatches.id"), unique=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("buyers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    subtotal_paise: Mapped[int] = mapped_column(BigInteger)
    tax_paise: Mapped[int] = mapped_column(BigInteger)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[InvoiceStatus] = mapped_column(
        str_enum(InvoiceStatus, "invoice_status"), default=InvoiceStatus.issued
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint("metres > 0", name="metres_positive"),
        CheckConstraint("rate_paise_per_m >= 0 AND amount_paise >= 0", name="amounts_non_negative"),
    )

    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    roll_id: Mapped[int] = mapped_column(ForeignKey("rolls.id"), unique=True)
    metres: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    rate_paise_per_m: Mapped[int] = mapped_column(BigInteger)
    amount_paise: Mapped[int] = mapped_column(BigInteger)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mode: Mapped[PaymentMode] = mapped_column(str_enum(PaymentMode, "payment_mode"))
    ref: Mapped[str | None] = mapped_column(String(60))


class WageRun(Base):
    __tablename__ = "wage_runs"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="period_order"),
        UniqueConstraint("period_start", "period_end"),
    )

    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[WageRunStatus] = mapped_column(
        str_enum(WageRunStatus, "wage_run_status"), default=WageRunStatus.draft
    )


class WageLine(Base):
    __tablename__ = "wage_lines"
    __table_args__ = (
        UniqueConstraint("wage_run_id", "worker_id"),
        CheckConstraint(
            "days >= 0 AND metres >= 0 AND amount_paise >= 0", name="amounts_non_negative"
        ),
    )

    wage_run_id: Mapped[int] = mapped_column(ForeignKey("wage_runs.id", ondelete="CASCADE"))
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    metres: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    amount_paise: Mapped[int] = mapped_column(BigInteger)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="amount_positive"),)

    date: Mapped[dt.date] = mapped_column(Date, index=True)
    category: Mapped[ExpenseCategory] = mapped_column(str_enum(ExpenseCategory, "expense_category"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text)
