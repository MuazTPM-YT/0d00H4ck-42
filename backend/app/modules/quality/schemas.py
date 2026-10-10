from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.enums import Stage
from app.core.errors import FieldError
from app.modules.quality.models import DefectType, QcDecision, RollStatus

# scanner retry key; same key twice returns the first answer
IdempotencyKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)
]
RollCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)
]


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


# 4-point system: each fault scores 1 to 4 by its length; a hole always scores 4
class DefectIn(BaseModel):
    type: DefectType
    count: int = Field(gt=0, le=999)
    points: int = Field(default=1, ge=1, le=4)

    @model_validator(mode="after")
    def hole_is_four(self):
        if self.type == DefectType.hole:
            self.points = 4
        return self


class QcCheckIn(BaseModel):
    decision: QcDecision
    defects: list[DefectIn] = Field(default_factory=list, max_length=20)
    shade_band: Literal["A", "B", "C"] | None = None
    gsm: Decimal | None = Field(None, gt=0, max_digits=7, decimal_places=2)
    width_cm: Decimal | None = Field(None, gt=0, max_digits=7, decimal_places=2)
    note: str | None = Field(None, max_length=500)
    # stage that redoes the roll; defaults to the last stage of the fabric's route
    rework_stage: Stage | None = None
    idempotency_key: IdempotencyKey | None = None

    # pass needs a shade band; rework or reject needs at least one defect to say why
    @model_validator(mode="after")
    def check_decision(self):
        if self.decision == QcDecision.pass_ and not self.shade_band:
            raise FieldError("shade_band", "Pick a shade band (A, B or C) to pass the roll")
        if self.decision != QcDecision.pass_ and not self.defects:
            raise FieldError("defects", "Mark at least one defect to rework or reject")
        if len({d.type for d in self.defects}) != len(self.defects):
            raise FieldError("defects", "List each defect type once, with its count")
        if self.rework_stage and self.decision != QcDecision.rework:
            raise FieldError("rework_stage", "Rework stage is only for rework")
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
    order_status: str
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


# --- trace and checks list


class DefectOut(BaseModel):
    type: str
    count: int
    points: int


# one check with the names and the 4-point score, for lists
class CheckOut(BaseModel):
    id: int
    roll_id: int
    roll_code: str
    order_id: int
    order_code: str
    loom_code: str
    length_m: Decimal
    at: datetime
    attempt_no: int
    decision: QcDecision
    defects: list[DefectOut]
    shade_band: str | None
    gsm: Decimal | None
    width_cm: Decimal | None
    notes: str | None
    inspector_name: str
    points: int
    score: Decimal | None


class TraceRoll(BaseModel):
    id: int
    code: str
    status: RollStatus
    length_m: Decimal
    shade_band: str | None
    dye_lot: str | None
    passed_at: datetime | None
    created_at: datetime
    location_code: str
    location_name: str


class TraceOrder(BaseModel):
    id: int
    code: str
    status: str
    buyer_name: str
    colour: str
    qty_m: Decimal
    deadline: date


class TraceFabric(BaseModel):
    code: str
    name: str
    width_cm: Decimal
    gsm: Decimal
    route: list[Stage]


class TraceRef(BaseModel):
    id: int
    code: str
    name: str


class TraceYarn(BaseModel):
    batch_id: int
    batch_code: str
    kg: Decimal
    yarn: str
    supplier_code: str
    supplier_name: str
    supplier_lot: str | None


class TraceEvent(BaseModel):
    at: datetime
    kind: str
    machine_code: str | None
    work_order_code: str | None
    note: str | None


class TraceJob(BaseModel):
    id: int
    code: str
    stage: Stage
    status: str
    machine_code: str | None


class TraceDispatch(BaseModel):
    id: int
    code: str
    status: str


class TraceOut(BaseModel):
    roll: TraceRoll
    order: TraceOrder
    fabric: TraceFabric
    loom: TraceRef
    shift: TraceRef
    weaver: TraceRef | None
    yarn: list[TraceYarn]
    checks: list[CheckOut]
    events: list[TraceEvent]
    rework_jobs: list[TraceJob]
    dispatch: TraceDispatch | None
    rework_stages: list[Stage]
