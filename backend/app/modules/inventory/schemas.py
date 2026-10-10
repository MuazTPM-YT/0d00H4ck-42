from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.enums import Source
from app.core.errors import FieldError
from app.core.types import Note, Paise, PositiveQty, ShortText
from app.modules.inventory.models import (
    BatchStatus,
    ExpectedDeliveryStatus,
    MoveReason,
    ReceiptStatus,
    ReservationStatus,
)
from app.modules.masters.models import LocationKind

Lot = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Vehicle = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        pattern=r"(?i)^[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{0,3}[ -]?\d{1,4}$",
    ),
]
BillNo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
IdemKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)]
Payload = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
MaxKg = Annotated[Decimal, Field(gt=0, le=100000, max_digits=12, decimal_places=3)]


# --- shared small shapes
class YarnItemRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fibre: str
    count: str
    colour: str


class SupplierRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str


class ReceiptRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    status: ReceiptStatus
    confirmed_at: datetime | None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    yarn_item_id: int | None
    supplier_id: int
    supplier_lot: str | None
    receipt_id: int
    received_kg: Decimal
    unit_cost_paise_per_kg: int
    status: BatchStatus
    order_id: int | None
    mismatch_notes: str | None
    created_at: datetime
    yarn_item: YarnItemRef | None = None
    supplier: SupplierRef | None = None
    receipt: ReceiptRef | None = None


# --- expected deliveries
class ExpectedDeliveryIn(BaseModel):
    supplier_id: int = Field(gt=0)
    yarn_item_id: int = Field(gt=0)
    expected_kg: MaxKg
    rate_paise_per_kg: Paise
    expected_date: date
    order_id: int | None = Field(default=None, gt=0)

    @field_validator("rate_paise_per_kg")
    @classmethod
    def rate_positive(cls, v: int) -> int:
        if v <= 0:
            raise FieldError("rate_paise_per_kg", "Rate must be greater than 0")
        return v

    @field_validator("expected_date")
    @classmethod
    def date_in_range(cls, v: date) -> date:
        today = date.today()
        if v < today - timedelta(days=7):
            raise FieldError("expected_date", "Date is more than a week in the past")
        if v > today + timedelta(days=365):
            raise FieldError("expected_date", "Date is more than a year away")
        return v


class ExpectedDeliveryOut(BaseModel):
    id: int
    supplier_id: int
    supplier_code: str
    supplier_name: str
    yarn_item_id: int
    label: str
    expected_kg: Decimal
    received_kg: Decimal
    rate_paise_per_kg: int
    order_id: int | None
    order_code: str | None
    expected_date: date
    status: ExpectedDeliveryStatus
    created_at: datetime


class ReasonIn(BaseModel):
    reason: Note


# --- scan check
class LabelCheckIn(BaseModel):
    payload: Payload
    expected_delivery_id: int | None = Field(default=None, gt=0)


class ComparisonRow(BaseModel):
    field: str
    expected: str
    actual: str
    ok: bool
    blocks: bool  # a failed blocking row quarantines the batch


class LabelOut(BaseModel):
    supplier_code: str
    supplier_lot: str
    fibre: str
    count: str
    colour: str
    label_kg: Decimal


class LabelCheckOut(BaseModel):
    label: LabelOut
    supplier: SupplierRef
    delivery: ExpectedDeliveryOut | None
    comparison: list[ComparisonRow]


class SampleLabel(BaseModel):
    delivery_id: int
    supplier: str
    kg: Decimal
    kind: str
    title: str
    payload: str


# --- receipts
class ReceiptIn(BaseModel):
    supplier_id: int | None = Field(default=None, gt=0)
    expected_delivery_id: int | None = Field(default=None, gt=0)
    vehicle_no: Vehicle | None = None
    bill_no: BillNo | None = None

    @model_validator(mode="after")
    def needs_source(self):
        if not self.supplier_id and not self.expected_delivery_id:
            raise FieldError("expected_delivery_id", "Pick the expected delivery or a supplier")
        return self


# one lot: a scan (payload), typed label fields, or "label missing" with just the weight
class ReceiptLineIn(BaseModel):
    payload: Payload | None = None
    supplier_lot: Lot | None = None
    fibre: ShortText | None = None
    count: ShortText | None = None
    colour: ShortText | None = None
    label_kg: MaxKg | None = None
    received_kg: MaxKg
    label_missing: bool = False
    rate_paise_per_kg: Paise | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.label_missing or self.payload:
            return self
        for name in ("supplier_lot", "fibre", "count", "colour", "label_kg"):
            if getattr(self, name) is None:
                raise FieldError(name, "Required when typing the label by hand")
        return self

    def label_fields(self) -> dict:
        return {
            "supplier_lot": self.supplier_lot,
            "fibre": self.fibre,
            "count": self.count,
            "colour": self.colour,
            "label_kg": self.label_kg,
        }


class ReceiptOut(BaseModel):
    id: int
    code: str
    supplier_id: int
    supplier_name: str
    expected_delivery: ExpectedDeliveryOut | None
    vehicle_no: str | None
    bill_no: str | None
    bill_amount_paise: int
    status: ReceiptStatus
    confirmed_at: datetime | None
    created_at: datetime
    batches: list[BatchOut]
    total_kg: Decimal


class ReceiptLineOut(BaseModel):
    batch: BatchOut
    created: bool  # false = same lot scanned again, existing batch returned
    comparison: list[ComparisonRow]


# --- batch detail
class MoveOut(BaseModel):
    id: int
    at: datetime
    qty: Decimal
    from_location: str
    to_location: str
    reason: MoveReason
    work_order_code: str | None
    source: Source


class BatchReservationOut(BaseModel):
    id: int
    order_id: int
    order_code: str
    kg: Decimal
    status: ReservationStatus


class ActivityOut(BaseModel):
    at: datetime
    action: str
    reason: str | None
    data: dict | None


class BatchDetailOut(BaseModel):
    batch: BatchOut
    where: dict[LocationKind, Decimal]
    moves: list[MoveOut]
    reservations: list[BatchReservationOut]
    activity: list[ActivityOut]


class IdentifyIn(BaseModel):
    yarn_item_id: int = Field(gt=0)
    supplier_lot: Lot | None = None


# --- stock
class StockRow(BaseModel):
    yarn_item_id: int
    label: str
    fibre: str
    count: str
    colour: str
    on_hand_kg: Decimal
    reserved_kg: Decimal
    free_kg: Decimal
    inspection_kg: Decimal
    quarantined_kg: Decimal
    wip_kg: Decimal
    needed_by_orders_kg: Decimal
    projected_free_kg: Decimal
    reorder_level_kg: Decimal
    level: str  # ok | low | short


class StockOut(BaseModel):
    items: list[StockRow]
    unidentified_kg: Decimal


# --- issue to production
class IssueIn(BaseModel):
    work_order_id: int = Field(gt=0)
    yarn_batch_id: int = Field(gt=0)
    kg: PositiveQty
    reason: Note | None = None
    source: Source = Source.manual
    idempotency_key: IdemKey | None = None


class ReturnIn(BaseModel):
    work_order_id: int = Field(gt=0)
    yarn_batch_id: int = Field(gt=0)
    kg: PositiveQty
    idempotency_key: IdemKey | None = None


class StockMoveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    at: datetime
    yarn_batch_id: int | None
    qty: Decimal
    reason: MoveReason
    ref_type: str | None
    ref_id: int | None


class PlanWorkOrder(BaseModel):
    id: int
    code: str
    stage: str
    status: str
    order_id: int
    order_code: str


class PlanLine(BaseModel):
    yarn_batch_id: int
    code: str
    supplier_lot: str | None
    label: str | None
    supplier: str
    received_at: datetime | None
    store_kg: Decimal
    reserved_for_order_kg: Decimal
    free_kg: Decimal
    issued_to_work_order_kg: Decimal


class OnFloor(BaseModel):
    yarn_batch_id: int
    code: str
    kg: Decimal


class IssuePlanOut(BaseModel):
    work_order: PlanWorkOrder
    reserved: list[PlanLine]
    free: list[PlanLine]
    on_floor: list[OnFloor]
