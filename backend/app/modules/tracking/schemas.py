from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class BuyerStage(StrEnum):
    order_received = "order_received"
    waiting_for_yarn = "waiting_for_yarn"
    in_production = "in_production"
    being_checked = "being_checked"
    ready_to_ship = "ready_to_ship"
    partly_shipped = "partly_shipped"
    shipped = "shipped"
    cancelled = "cancelled"


class Risk(StrEnum):
    on_track = "on_track"
    at_risk = "at_risk"
    late = "late"


# buyer link: good fabric only, rejects stay inside the mill
class BuyerMetres(BaseModel):
    produced: Decimal
    in_qc: Decimal
    passed: Decimal
    shipped: Decimal


class Metres(BuyerMetres):
    rejected: Decimal


class TimelineEvent(BaseModel):
    at: datetime
    title: str


# what a buyer sees: no costs, no rates, no internal ids
class TrackOut(BaseModel):
    order_code: str
    fabric: str
    colour: str
    qty_m: Decimal
    deadline: date
    stage: BuyerStage
    production_stage: str | None
    progress_pct: int | None
    metres: BuyerMetres
    projected_finish: date | None
    risk: Risk | None
    timeline: list[TimelineEvent]


class RollRow(BaseModel):
    id: int
    code: str
    length_m: Decimal
    status: str
    shade_band: str | None
    dispatch_code: str | None


class DispatchRef(BaseModel):
    id: int
    code: str
    status: str
    vehicle_no: str | None
    confirmed_at: datetime | None
    roll_count: int
    metres: Decimal


class InvoiceRef(BaseModel):
    id: int
    code: str
    total_paise: int
    paid_paise: int
    status: str
    due_date: date


# office view of one order: the buyer card plus the records behind it
class OrderView(TrackOut):
    metres: Metres
    order_id: int
    order_status: str
    buyer_name: str
    tracking_token: str
    rolls: list[RollRow]
    dispatches: list[DispatchRef]
    invoices: list[InvoiceRef]


class StageRow(BaseModel):
    order_id: int
    stage: BuyerStage
    production_stage: str | None
    progress_pct: int | None
    passed_m: Decimal
    shipped_m: Decimal
