from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.orders.models import OrderStatus


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    buyer_id: int
    fabric_type_id: int
    colour: str
    qty_m: Decimal
    rate_paise_per_m: int
    deadline: date
    status: OrderStatus
    confirmed_at: datetime | None
    created_at: datetime


class YarnLine(BaseModel):
    fibre: str
    count: str
    colour: str
    kg_needed: Decimal
    kg_free: Decimal
    kg_short: Decimal
