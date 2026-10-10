from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.enums import Source, Stage, Unit
from app.core.errors import FieldError
from app.core.types import Note, PositiveQty
from app.modules.production.models import MachineStatus, WorkOrderStatus
from app.modules.quality.models import RollStatus

Id = Annotated[int, Field(gt=0)]
# scanner or machine feed retry key; same key twice returns the first response
IdempotencyKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=8, max_length=100)
]


class WorkOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    order_id: int
    stage: Stage
    seq: int
    machine_id: int | None
    planned_qty: Decimal
    unit: Unit
    status: WorkOrderStatus
    queue_position: int | None
    roll_id: int | None
    started_at: datetime | None
    finished_at: datetime | None


class OpenWorkOrderOut(WorkOrderOut):
    order_code: str
    deadline: date
    produced: Decimal


class MachineEventIn(BaseModel):
    machine_id: Id
    status: MachineStatus
    reason: Note | None = None
    source: Source = Source.manual
    idempotency_key: IdempotencyKey | None = None

    @model_validator(mode="after")
    def downtime_needs_reason(self):
        if self.status in (MachineStatus.breakdown, MachineStatus.maintenance) and not self.reason:
            raise FieldError("reason", f"Give a reason for {self.status}")
        return self


class MachineEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_id: int
    at: datetime
    status: MachineStatus
    reason: str | None
    work_order_id: int | None
    source: Source


class QueueIn(BaseModel):
    machine_id: Id


class ReorderIn(BaseModel):
    work_order_ids: list[Id] = Field(min_length=1, max_length=200)


class MoveIn(BaseModel):
    machine_id: Id
    reason: Note


class OutputIn(BaseModel):
    machine_id: Id
    qty: PositiveQty
    work_order_id: Id | None = None
    shift_id: Id | None = None
    worker_id: Id | None = None
    # a counter that buffered offline sends when the metres were made
    at: datetime | None = None
    source: Source = Source.manual
    idempotency_key: IdempotencyKey | None = None

    @model_validator(mode="after")
    def at_is_recent(self):
        if self.at:
            if self.at.tzinfo is None:
                raise FieldError("at", "Time needs a timezone")
            now = datetime.now(UTC)
            if self.at > now + timedelta(minutes=5):
                raise FieldError("at", "Time cannot be in the future")
            if self.at < now - timedelta(hours=24):
                raise FieldError("at", "Output older than 24 hours needs a manual correction")
        return self


class ProductionLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: int
    machine_id: int
    shift_id: int
    worker_id: int | None
    qty: Decimal
    unit: Unit
    at: datetime
    source: Source


class RollIn(BaseModel):
    work_order_id: Id
    length_m: Annotated[Decimal, Field(gt=0, le=1000, max_digits=12, decimal_places=3)]
    shift_id: Id | None = None
    weaver_id: Id | None = None
    source: Source = Source.manual
    idempotency_key: IdempotencyKey | None = None


class RollProcessIn(BaseModel):
    work_order_id: Id
    source: Source = Source.manual
    idempotency_key: IdempotencyKey | None = None


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


class BoardJob(BaseModel):
    work_order_id: int
    code: str
    order_id: int
    order_code: str
    stage: Stage
    status: WorkOrderStatus
    planned: Decimal
    produced: Decimal
    unit: Unit
    rework: bool


class BoardTile(BaseModel):
    machine_id: int
    code: str
    name: str
    type: Stage
    unit: Unit
    status: MachineStatus
    since: datetime | None
    reason: str | None
    job: BoardJob | None
    today_output: Decimal
    queued: int
    crew: list[str]


class BoardOut(BaseModel):
    as_of: datetime
    shift_code: str | None
    machines: list[BoardTile]


class TimelineOut(BaseModel):
    machine_id: int
    code: str
    date: date
    unit: Unit
    events: list[MachineEventOut]
    seconds: dict[str, float]
    output: list[ProductionLogOut]
    total_output: Decimal
