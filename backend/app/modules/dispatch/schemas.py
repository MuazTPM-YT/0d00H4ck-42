from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.dispatch.models import DispatchStatus


class DispatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    order_id: int
    buyer_id: int
    vehicle_no: str | None
    driver: str | None
    status: DispatchStatus
    confirmed_at: datetime | None
    created_at: datetime
