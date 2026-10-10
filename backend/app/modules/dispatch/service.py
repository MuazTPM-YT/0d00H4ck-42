from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import Page, paginate
from app.modules.dispatch.models import Dispatch, DispatchStatus
from app.modules.quality.models import Roll

DISPATCH_TRANSITIONS = {
    DispatchStatus.draft: {DispatchStatus.loading},
    DispatchStatus.loading: {DispatchStatus.confirmed, DispatchStatus.draft},
}


def list_dispatches(db: Session, page: Page, status: DispatchStatus | None = None) -> dict:
    stmt = select(Dispatch).order_by(Dispatch.id.desc())
    if status:
        stmt = stmt.where(Dispatch.status == status)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# rolls on the shelf: passed QC, not on any dispatch; optional order / shade band filter
def finished_stock(
    db: Session, order_id: int | None = None, shade_band: str | None = None
) -> list[Roll]:
    raise NotImplementedError("dispatch.finished_stock")
