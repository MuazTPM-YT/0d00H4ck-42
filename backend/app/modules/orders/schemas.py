from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.dates import mill_today
from app.core.errors import FieldError
from app.core.types import Paise, ShortText
from app.modules.orders.models import OrderStatus

OrderMetres = Annotated[Decimal, Field(gt=0, le=1_000_000, max_digits=12, decimal_places=3)]


class NamedRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    buyer_id: int
    fabric_type_id: int
    colour: str
    qty_m: Decimal
    rate_paise_per_m: int | None  # None for roles that do not see money
    deadline: date
    status: OrderStatus
    confirmed_at: datetime | None
    created_at: datetime
    buyer: NamedRef | None = None
    fabric_type: NamedRef | None = None


class YarnLine(BaseModel):
    fibre: str
    count: str
    colour: str
    kg_needed: Decimal
    kg_free: Decimal
    kg_short: Decimal


class RequirementIn(BaseModel):
    fabric_type_id: int = Field(gt=0)
    colour: ShortText
    qty_m: OrderMetres


class OrderIn(RequirementIn):
    buyer_id: int = Field(gt=0)
    rate_paise_per_m: Paise
    deadline: date

    @field_validator("rate_paise_per_m")
    @classmethod
    def rate_positive(cls, v: int) -> int:
        if v <= 0:
            raise FieldError("rate_paise_per_m", "Rate must be greater than 0")
        return v

    @field_validator("deadline")
    @classmethod
    def deadline_ahead(cls, v: date) -> date:
        today = mill_today()
        if v <= today:
            raise FieldError("deadline", "Deadline must be after today")
        if v > today + timedelta(days=730):
            raise FieldError("deadline", "Deadline is more than two years away")
        return v


class LotOut(BaseModel):
    yarn_batch_id: int
    code: str
    supplier_lot: str | None
    supplier: str
    reserved_kg: Decimal
    consumed_kg: Decimal


class AllocationLine(YarnLine):
    yarn_item_id: int | None
    kg_reserved: Decimal
    kg_issued: Decimal
    lots: list[LotOut]
    mixed_lots: bool  # more than one supplier lot: barre risk


class AllocationOut(BaseModel):
    order_id: int
    code: str
    status: OrderStatus
    lines: list[AllocationLine]
    mixed_lots: bool
    fully_covered: bool


class ToBuyRow(BaseModel):
    order_id: int
    order_code: str
    buyer: str
    deadline: date
    yarn_item_id: int | None
    label: str
    short_kg: Decimal  # not reserved and not issued yet
    free_cover_kg: Decimal  # free stock can cover this now: press Reserve
    on_order_kg: Decimal
    to_buy_kg: Decimal
    suggested_supplier_id: int | None
    suggested_rate_paise_per_kg: int | None
