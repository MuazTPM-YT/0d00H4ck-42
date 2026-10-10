from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.inventory.models import BatchStatus


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    yarn_item_id: int | None
    supplier_id: int
    supplier_lot: str | None
    receipt_id: int
    received_kg: Decimal
    unit_cost_paise_per_kg: int
    status: BatchStatus
    order_id: int | None
    mismatch_notes: str | None
    created_at: datetime
