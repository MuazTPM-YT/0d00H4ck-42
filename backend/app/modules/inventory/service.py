from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Source
from app.core.pagination import Page, paginate
from app.modules.inventory.models import (
    BatchStatus,
    ExpectedDeliveryStatus,
    ReceiptStatus,
    Reservation,
    ReservationStatus,
    StockMove,
    YarnBatch,
)

BATCH_TRANSITIONS = {
    BatchStatus.pending_identification: {
        BatchStatus.inspection,
        BatchStatus.quarantined,
        BatchStatus.rejected,
    },
    BatchStatus.inspection: {BatchStatus.approved, BatchStatus.quarantined, BatchStatus.rejected},
    BatchStatus.quarantined: {BatchStatus.approved, BatchStatus.rejected},
    BatchStatus.approved: {BatchStatus.quarantined},
}
RECEIPT_TRANSITIONS = {ReceiptStatus.draft: {ReceiptStatus.confirmed}}
EXPECTED_DELIVERY_TRANSITIONS = {
    ExpectedDeliveryStatus.open: {
        ExpectedDeliveryStatus.partially_received,
        ExpectedDeliveryStatus.received,
        ExpectedDeliveryStatus.cancelled,
    },
    ExpectedDeliveryStatus.partially_received: {
        ExpectedDeliveryStatus.received,
        ExpectedDeliveryStatus.cancelled,
    },
}
RESERVATION_TRANSITIONS = {
    ReservationStatus.active: {ReservationStatus.consumed, ReservationStatus.released},
}


def list_batches(db: Session, page: Page, status: BatchStatus | None = None) -> dict:
    stmt = select(YarnBatch).order_by(YarnBatch.id.desc())
    if status:
        stmt = stmt.where(YarnBatch.status == status)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# approved kg sitting in store locations for this yarn item (ledger sum, approved batches only)
def stock_on_hand(db: Session, yarn_item_id: int) -> Decimal:
    raise NotImplementedError("inventory.stock_on_hand")


# stock_on_hand minus active reservations
def free_stock(db: Session, yarn_item_id: int) -> Decimal:
    raise NotImplementedError("inventory.free_stock")


# reserve the order's yarn requirement; lock batch rows, prefer one supplier lot per component
def reserve(db: Session, order_id: int, user_id: int) -> list[Reservation]:
    raise NotImplementedError("inventory.reserve")


# move reserved yarn from store to WIP for one work order; over-issue needs a reason
def issue_to_work_order(
    db: Session,
    work_order_id: int,
    yarn_batch_id: int,
    kg: Decimal,
    user_id: int,
    source: Source = Source.manual,
    idempotency_key: str | None = None,
    reason: str | None = None,
) -> StockMove:
    raise NotImplementedError("inventory.issue_to_work_order")
