from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.enums import Stage, Unit
from app.modules.analytics.models import InsightStatus, Severity

Risk = Literal["on_track", "at_risk", "late"]


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    severity: Severity
    entity_type: str
    entity_id: int
    title: str
    facts: dict
    narrative: str | None
    status: InsightStatus
    created_at: datetime


class PlannedStage(BaseModel):
    work_order_id: int
    code: str
    stage: Stage
    remaining: float
    unit: Unit
    machine: str | None
    start: datetime | None
    end: datetime | None


class Basis(BaseModel):
    # machine code -> {"per_hour": 61.2, "from": "median of 6 shifts" | "rated speed"}
    throughputs: dict[str, dict]
    qc_hours: int
    dispatch_hours: int
    repair_hours: float
    rule: str


class DeliveryEstimateOut(BaseModel):
    order_id: int
    order_code: str
    deadline: date
    expected_at: datetime | None
    status: Risk
    slack_hours: float | None
    blocked_by: list[str]
    stages: list[PlannedStage]
    basis: Basis
