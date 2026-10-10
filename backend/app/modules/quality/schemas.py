from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.quality.models import RollStatus


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
