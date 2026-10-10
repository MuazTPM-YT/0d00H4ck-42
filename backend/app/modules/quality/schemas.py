from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import FieldError
from app.modules.quality.models import DefectType, QcDecision, RollStatus


class RollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    order_id: int
    work_order_id: int
    loom_machine_id: int
    shift_id: int
    weaver_id: int | None
    length_m: Decimal
    status: RollStatus
    shade_band: str | None
    dye_lot: str | None
    location_id: int
    passed_at: datetime | None
    created_at: datetime


class DefectIn(BaseModel):
    type: DefectType
    count: int = Field(gt=0, le=999)


class QcCheckIn(BaseModel):
    decision: QcDecision
    defects: list[DefectIn] = Field(default_factory=list, max_length=20)
    shade_band: Literal["A", "B", "C"] | None = None
    gsm: Decimal | None = Field(None, gt=0, max_digits=7, decimal_places=2)
    width_cm: Decimal | None = Field(None, gt=0, max_digits=7, decimal_places=2)
    note: str | None = Field(None, max_length=500)

    # pass needs a shade band; rework or reject needs at least one defect to say why
    @model_validator(mode="after")
    def check_decision(self):
        if self.decision == QcDecision.pass_ and not self.shade_band:
            raise FieldError("shade_band", "Pick a shade band (A, B or C) to pass the roll")
        if self.decision != QcDecision.pass_ and not self.defects:
            raise FieldError("defects", "Mark at least one defect to rework or reject")
        return self


class QcCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    roll_id: int
    inspector_id: int
    at: datetime
    attempt_no: int
    decision: QcDecision
    defects: list[dict]
    shade_band: str | None
    gsm: Decimal | None
    width_cm: Decimal | None
    notes: str | None


class QcResultOut(BaseModel):
    check: QcCheckOut
    roll: RollOut
    rework_work_order_id: int | None = None


# one roll with the names a QC inspector needs, no extra lookups
class RollRowOut(BaseModel):
    id: int
    code: str
    status: RollStatus
    length_m: Decimal
    shade_band: str | None
    order_id: int
    order_code: str
    buyer_name: str
    fabric_name: str
    fabric_gsm: Decimal
    fabric_width_cm: Decimal
    colour: str
    loom_code: str
    shift_name: str
    weaver_name: str | None
    created_at: datetime
    waiting_since: datetime


class RollDetailOut(RollRowOut):
    checks: list[QcCheckOut]


class DecisionCounts(BaseModel):
    passed: int = 0
    rework: int = 0
    rejected: int = 0


class DefectGroup(BaseModel):
    key: str
    checks: int
    defects: int


class QualitySummaryOut(BaseModel):
    days: int
    waiting: int
    first_attempt: DecisionCounts
    all_attempts: DecisionCounts
    pass_rate_pct: float | None
    defects_by_type: dict[str, int]
    by_machine: list[DefectGroup]
    by_order: list[DefectGroup]
