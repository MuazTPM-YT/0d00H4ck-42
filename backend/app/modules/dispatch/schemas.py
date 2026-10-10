from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.types import Name, Note
from app.modules.dispatch.models import DispatchStatus

# "KA-01-AB-1234", "MH12 DE 4521": letters, digits, spaces, dashes
VehicleNo = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, pattern=r"(?i)^[A-Z0-9][A-Z0-9 -]{3,18}[A-Z0-9]$"
    ),
]
RollCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)
]
ScanKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)]
Otp = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]
Receiver = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
DeliveryNote = Annotated[
    str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


class DispatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    order_id: int
    buyer_id: int
    vehicle_no: str | None
    driver: str | None
    driver_email: str | None
    status: DispatchStatus
    confirmed_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


# gone-out register row: dispatch + who, what and how much
class DispatchRow(DispatchOut):
    order_code: str
    buyer_name: str
    roll_count: int
    metres: Decimal
    invoice_id: int | None
    invoice_code: str | None


class DispatchCreate(BaseModel):
    order_id: int = Field(gt=0)
    vehicle_no: VehicleNo | None = None
    driver: Name | None = None
    driver_email: EmailStr | None = None


class VehicleIn(BaseModel):
    vehicle_no: VehicleNo
    driver: Name | None = None
    driver_email: EmailStr | None = None


# resend the driver link, optionally to a corrected address (the truck itself is locked)
class DriverEmailIn(BaseModel):
    driver_email: EmailStr | None = None


# newest try at emailing the driver link
class MailTry(BaseModel):
    status: str
    at: datetime
    to: str | None
    error: str | None


class ScanIn(BaseModel):
    roll_code: RollCode
    idempotency_key: ScanKey | None = None


class OverrideIn(BaseModel):
    reason: Note


class ShelfRoll(BaseModel):
    id: int
    code: str
    order_id: int
    length_m: Decimal
    shade_band: str | None
    location: str
    days_on_shelf: int
    dispatch_code: str | None


class ShelfGroup(BaseModel):
    order_id: int
    order_code: str
    buyer_name: str
    order_open: bool
    ordered_m: Decimal
    shipped_m: Decimal
    on_shelf_m: Decimal
    rolls: list[ShelfRoll]


class CornerItem(BaseModel):
    roll_id: int
    roll_code: str
    order_code: str
    length_m: Decimal
    days_on_shelf: int
    reasons: list[str]


class Proposal(BaseModel):
    band: str | None
    roll_ids: list[int]
    total_m: Decimal
    need_m: Decimal
    overshoot_m: Decimal
    short_m: Decimal


class LoadedRoll(BaseModel):
    id: int
    code: str
    length_m: Decimal
    shade_band: str | None
    location: str


class DispatchDetail(DispatchOut):
    order_code: str
    buyer_name: str
    buyer_gstin: str
    buyer_city: str | None
    fabric: str
    colour: str
    ordered_m: Decimal
    shipped_m: Decimal
    remaining_m: Decimal
    loaded: list[LoadedRoll]
    loaded_m: Decimal
    bands: list[str]
    shade_override: str | None
    proposal: Proposal | None
    candidates: list[LoadedRoll]
    invoice_id: int | None
    invoice_code: str | None
    # driver link key once the truck has left; the code itself never reaches staff
    delivery_token: str | None
    received_by: str | None
    delivery_note: str | None
    has_code: bool
    tries_left: int
    mail_on: bool
    driver_mail: MailTry | None


# buyer's code, read off the buyer link; the office path takes the same body
class DeliverIn(BaseModel):
    otp: Otp
    received_by: Receiver
    note: DeliveryNote | None = None


class DeliveryRoll(BaseModel):
    code: str
    length_m: Decimal


# driver page: what is on the truck and where it goes; no money, no code
class DeliveryOut(BaseModel):
    challan: str
    order_code: str
    buyer_name: str
    buyer_city: str | None
    fabric: str
    colour: str
    vehicle_no: str | None
    driver: str | None
    left_at: datetime
    rolls: list[DeliveryRoll]
    roll_count: int
    metres: Decimal
    delivered_at: datetime | None
    received_by: str | None
    delivery_note: str | None
    tries_left: int
    has_code: bool


class ScanResult(BaseModel):
    dispatch_id: int
    status: DispatchStatus
    roll_code: str
    roll_count: int
    loaded_m: Decimal
    remaining_m: Decimal
    bands: list[str]
