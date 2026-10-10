from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.enums import Source, Stage, Unit
from app.core.errors import FieldError
from app.core.types import Note
from app.modules.production.models import MachineStatus, WorkOrderStatus

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
