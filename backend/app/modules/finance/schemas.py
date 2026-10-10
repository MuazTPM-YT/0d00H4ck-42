from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.modules.finance.models import InvoiceStatus


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    dispatch_id: int
    buyer_id: int
    order_id: int
    subtotal_paise: int
    tax_paise: int
    total_paise: int
    issued_at: datetime
    due_date: date
    status: InvoiceStatus
