from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.errors import FieldError
from app.core.types import Note
from app.modules.finance.models import ExpenseCategory, InvoiceStatus, PaymentMode, WageRunStatus

Amount = Annotated[int, Field(gt=0, le=10**12)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    dispatch_id: int
    buyer_id: int
    order_id: int
    subtotal_paise: int
    tax_paise: int
    total_paise: int
    issued_at: datetime
    due_date: date
    status: InvoiceStatus


# list row: invoice + who owes and how much is still open
class InvoiceRow(InvoiceOut):
    buyer_name: str
    order_code: str
    dispatch_code: str
    paid_paise: int
    outstanding_paise: int
    days_overdue: int


class InvoiceLineOut(BaseModel):
    roll_code: str
    shade_band: str | None
    metres: Decimal
    rate_paise_per_m: int
    amount_paise: int


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    amount_paise: int
    received_at: datetime
    mode: PaymentMode
    ref: str | None


class InvoiceDetail(InvoiceRow):
    buyer_gstin: str
    buyer_city: str | None
    fabric: str
    colour: str
    vehicle_no: str | None
    gst_pct: Decimal
    lines: list[InvoiceLineOut]
    payments: list[PaymentOut]


class PaymentIn(BaseModel):
    invoice_id: int
    amount_paise: Amount
    received_on: date
    mode: PaymentMode
    ref: Ref | None = None

    @model_validator(mode="after")
    def not_in_future(self):
        if self.received_on > date.today():
            raise FieldError("received_on", "Payment date cannot be in the future")
        return self


class PaymentRow(PaymentOut):
    invoice_code: str
    buyer_name: str


class WageRunIn(BaseModel):
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def sane_period(self):
        if self.period_end < self.period_start:
            raise FieldError("period_end", "End date must be on or after start date")
        if (self.period_end - self.period_start).days > 62:
            raise FieldError("period_end", "A wage run covers at most 62 days")
        if self.period_end > date.today():
            raise FieldError("period_end", "Cannot pay wages for days that have not happened")
        return self


class WageLineOut(BaseModel):
    worker_id: int
    worker_code: str
    worker_name: str
    wage_type: str
    rate_paise: int
    days: Decimal
    metres: Decimal
    amount_paise: int


class WageRunOut(BaseModel):
    id: int
    period_start: date
    period_end: date
    status: WageRunStatus
    workers: int
    total_paise: int
    created_at: datetime


class WageRunDetail(WageRunOut):
    lines: list[WageLineOut]


class ExpenseIn(BaseModel):
    date: date
    category: ExpenseCategory
    amount_paise: Amount
    note: Note | None = None

    @model_validator(mode="after")
    def not_in_future(self):
        if self.date > date.today():
            raise FieldError("date", "Expense date cannot be in the future")
        return self


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: date
    category: ExpenseCategory
    amount_paise: int
    note: str | None


class CostLine(BaseModel):
    label: str
    detail: str
    amount_paise: int


class OrderCost(BaseModel):
    order_id: int
    order_code: str
    yarn_paise: int
    machine_paise: int
    labour_paise: int
    total_paise: int
    yarn: list[CostLine]
    machine: list[CostLine]
    labour: list[CostLine]
    produced_m: Decimal
    passed_m: Decimal
    rejected_m: Decimal
    passed_rolls: int
    reject_share_paise: int
    cost_per_m_paise: int | None
    cost_per_roll_paise: int | None
    invoiced_paise: int
    margin_paise: int | None
    rules: list[str]


class MachineDay(BaseModel):
    day: date
    qty: Decimal


class MachineProduction(BaseModel):
    machine_id: int
    code: str
    name: str
    unit: str
    month_qty: Decimal
    days: list[MachineDay]
    hours: dict[str, Decimal]


class MonthView(BaseModel):
    month: str
    invoiced_paise: int
    invoiced_ex_gst_paise: int
    received_paise: int
    yarn_bills_paise: int
    wages_accrued_paise: int
    wages_paid_paise: int
    expenses_paise: int
    result_invoiced_paise: int
    result_cash_paise: int
    notes: list[str]


class MonthRecord(BaseModel):
    on: date
    ref: str
    party: str
    amount_paise: int
    link: str | None
