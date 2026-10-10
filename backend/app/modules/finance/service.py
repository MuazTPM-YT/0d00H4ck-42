from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import Page, paginate
from app.modules.finance.models import Invoice, InvoiceStatus, WageRunStatus

# invoice status follows payments: never set by hand
INVOICE_TRANSITIONS = {
    InvoiceStatus.issued: {InvoiceStatus.part_paid, InvoiceStatus.paid},
    InvoiceStatus.part_paid: {InvoiceStatus.paid},
}
WAGE_RUN_TRANSITIONS = {
    WageRunStatus.draft: {WageRunStatus.final},
    WageRunStatus.final: {WageRunStatus.paid},
}


def list_invoices(db: Session, page: Page, status: InvoiceStatus | None = None) -> dict:
    stmt = select(Invoice).order_by(Invoice.id.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# yarn (FIFO GRN cost) + labour + machine hours + rework/reject cost, vs invoiced revenue
def order_cost(db: Session, order_id: int) -> dict:
    raise NotImplementedError("finance.order_cost")
