from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class BuyerStage(StrEnum):
    confirmed = "confirmed"
    in_production = "in_production"
    quality_check = "quality_check"
    ready_to_ship = "ready_to_ship"
    dispatched = "dispatched"
    cancelled = "cancelled"


# what a buyer sees: no costs, no internal ids
class TrackOut(BaseModel):
    order_code: str
    fabric: str
    colour: str
    qty_m: Decimal
    deadline: date
    stage: BuyerStage
    production_stage: str | None
    metres: dict[str, Decimal]
    projected_finish: date | None
