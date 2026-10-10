from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.codes import next_code
from app.core.pagination import Page, paginate
from app.core.units import line_amount_paise
from app.modules.finance.models import Invoice, InvoiceLine, InvoiceStatus, WageRunStatus
from app.modules.orders.models import Order

# GST on cotton fabric (HSN 5208); moves to Settings when core takes the schema request
GST_PCT = Decimal(5)
DUE_DAYS = 30

# invoice status follows payments: never set by hand
INVOICE_TRANSITIONS = {
    InvoiceStatus.issued: {InvoiceStatus.part_paid, InvoiceStatus.paid},
    InvoiceStatus.part_paid: {InvoiceStatus.paid},
}
WAGE_RUN_TRANSITIONS = {
    WageRunStatus.draft: {WageRunStatus.final},
    WageRunStatus.final: {WageRunStatus.paid},
}


def gst_paise(subtotal_paise: int) -> int:
    return int((Decimal(subtotal_paise) * GST_PCT / 100).quantize(Decimal(1), ROUND_HALF_UP))


def list_invoices(db: Session, page: Page, status: InvoiceStatus | None = None) -> dict:
    stmt = select(Invoice).order_by(Invoice.id.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# invoice for one confirmed dispatch: one line per loaded roll at the order rate, GST on top
def issue_invoice(db: Session, user_id: int, dispatch, rolls: list) -> Invoice:
    order = db.get(Order, dispatch.order_id)
    lines = [
        InvoiceLine(
            roll_id=r.id,
            metres=r.length_m,
            rate_paise_per_m=order.rate_paise_per_m,
            amount_paise=line_amount_paise(order.rate_paise_per_m, r.length_m),
        )
        for r in rolls
    ]
    subtotal = sum(line.amount_paise for line in lines)
    tax = gst_paise(subtotal)
    invoice = Invoice(
        code=next_code(db, "INV"),
        dispatch_id=dispatch.id,
        buyer_id=dispatch.buyer_id,
        order_id=order.id,
        subtotal_paise=subtotal,
        tax_paise=tax,
        total_paise=subtotal + tax,
        issued_at=dispatch.confirmed_at,
        due_date=(dispatch.confirmed_at + timedelta(hours=5, minutes=30)).date()
        + timedelta(days=DUE_DAYS),
        status=InvoiceStatus.issued,
    )
    db.add(invoice)
    db.flush()
    for line in lines:
        line.invoice_id = invoice.id
    db.add_all(lines)
    db.flush()
    audit.record(
        db, user_id, "issue", "invoices", invoice.id, data={"total_paise": invoice.total_paise}
    )
    return invoice


# yarn (FIFO GRN cost) + labour + machine hours + rework/reject cost, vs invoiced revenue
def order_cost(db: Session, order_id: int) -> dict:
    raise NotImplementedError("finance.order_cost")
