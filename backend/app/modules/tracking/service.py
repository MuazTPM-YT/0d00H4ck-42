from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.orders.models import Order


def order_by_token(db: Session, token: str) -> Order:
    order = db.scalar(select(Order).where(Order.tracking_token == token))
    if not order:
        raise NotFound("Tracking link is not valid")
    return order


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# buyer stage derived from work orders, rolls and dispatches + metres in each bucket
def order_stage(db: Session, order_id: int) -> dict:
    raise NotImplementedError("tracking.order_stage")
