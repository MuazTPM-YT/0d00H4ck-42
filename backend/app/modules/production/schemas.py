from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.enums import Stage, Unit
from app.modules.production.models import WorkOrderStatus


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
