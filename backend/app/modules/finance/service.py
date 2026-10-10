from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.enums import Stage, Unit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import line_amount_paise, qty
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch
from app.modules.finance.models import (
    Expense,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    WageLine,
    WageRun,
    WageRunStatus,
)
from app.modules.inventory.models import (
    ItemKind,
    MoveReason,
    Receipt,
    ReceiptStatus,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import (
    Buyer,
    FabricType,
    Machine,
    Shift,
    Supplier,
    WageType,
    Worker,
)
from app.modules.orders.models import Order
from app.modules.production.models import MachineEvent, MachineStatus, ProductionLog, WorkOrder
from app.modules.quality.models import Roll, RollStatus
from app.modules.workforce.models import Attendance, AttendanceStatus, CrewAssignment

# invoice status follows payments: never set by hand
INVOICE_TRANSITIONS = {
    InvoiceStatus.issued: {InvoiceStatus.part_paid, InvoiceStatus.paid},
    InvoiceStatus.part_paid: {InvoiceStatus.paid},
}
WAGE_RUN_TRANSITIONS = {
    WageRunStatus.draft: {WageRunStatus.final},
    WageRunStatus.final: {WageRunStatus.paid},
}
# GST on cotton fabric (HSN 5208); moves to Settings when core takes the schema request
GST_PCT = Decimal(5)
DUE_DAYS = 30
IST = timezone(timedelta(hours=5, minutes=30))
ZERO = Decimal(0)
DAY_FACTOR = {AttendanceStatus.present: Decimal(1), AttendanceStatus.half_day: Decimal("0.5")}
COST_RULES = [
    "Yarn: every kg issued to this order's work orders, priced at the GRN cost of the batch it "
    "came from (batches are the cost layers, issued oldest first), minus kg returned.",
    "Machine: hours each machine ran this order's work orders (from the machine event log) "
    "x the machine's hourly cost.",
    "Labour: piece-rated weavers get metres they wove for this order x their piece rate. "
    "Daily-rated crew get their day rate split by the hours their machine ran this order "
    "in their shift.",
    "Rework and rejected rolls used real yarn, machine and labour, so they stay in the cost. "
    "Cost per metre = total cost / metres that passed QC.",
    "Margin = invoiced value before GST - total cost.",
]


def _ist_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time(), IST), datetime.combine(
        end + timedelta(days=1), time(), IST
    )


def _month_dates(month: str) -> tuple[date, date]:
    first = date.fromisoformat(f"{month}-01")
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _hours(a: datetime, b: datetime) -> Decimal:
    return Decimal((b - a).total_seconds()) / 3600


def _ist_date(at: datetime) -> date:
    return at.astimezone(IST).date()


def _rs(paise: int) -> str:
    return f"Rs {Decimal(paise) / 100:,.2f}"


def gst_paise(subtotal_paise: int) -> int:
    return int((Decimal(subtotal_paise) * GST_PCT / 100).quantize(Decimal(1), ROUND_HALF_UP))


# --- machine time: each event lasts until the next event of that machine


@dataclass
class Span:
    machine_id: int
    status: MachineStatus
    work_order_id: int | None
    start: datetime
    end: datetime


def machine_spans(
    db: Session, machine_ids: list[int], start: datetime, end: datetime
) -> list[Span]:
    end = min(end, datetime.now(UTC))
    rows = db.scalars(
        select(MachineEvent)
        .where(MachineEvent.machine_id.in_(machine_ids or [0]), MachineEvent.at < end)
        .order_by(MachineEvent.machine_id, MachineEvent.at, MachineEvent.id)
    ).all()
    spans = []
    for i, e in enumerate(rows):
        same = i + 1 < len(rows) and rows[i + 1].machine_id == e.machine_id
        a, b = max(e.at, start), min(rows[i + 1].at if same else end, end)
        if b > a:
            spans.append(Span(e.machine_id, e.status, e.work_order_id, a, b))
    return spans


# --- invoices and payments


def _paid_subquery():
    return (
        select(Payment.invoice_id, func.sum(Payment.amount_paise).label("paid"))
        .group_by(Payment.invoice_id)
        .subquery()
    )


def _invoice_row(inv: Invoice, buyer: str, order: str, dispatch: str, paid: int) -> dict:
    today = datetime.now(IST).date()
    outstanding = inv.total_paise - paid
    return {
        **{c: getattr(inv, c) for c in ("id", "code", "dispatch_id", "buyer_id", "order_id")},
        **{c: getattr(inv, c) for c in ("subtotal_paise", "tax_paise", "total_paise")},
        **{c: getattr(inv, c) for c in ("issued_at", "due_date", "status")},
        "buyer_name": buyer,
        "order_code": order,
        "dispatch_code": dispatch,
        "paid_paise": paid,
        "outstanding_paise": outstanding,
        "days_overdue": max((today - inv.due_date).days, 0) if outstanding else 0,
    }


def _invoice_stmt():
    paid = _paid_subquery()
    return (
        select(Invoice, Buyer.name, Order.code, Dispatch.code, func.coalesce(paid.c.paid, 0))
        .join(Buyer, Buyer.id == Invoice.buyer_id)
        .join(Order, Order.id == Invoice.order_id)
        .join(Dispatch, Dispatch.id == Invoice.dispatch_id)
        .outerjoin(paid, paid.c.invoice_id == Invoice.id)
    )


def list_invoices(
    db: Session,
    page: Page,
    status: InvoiceStatus | None = None,
    outstanding: bool = False,
    buyer_id: int | None = None,
    order_id: int | None = None,
) -> dict:
    stmt = _invoice_stmt()
    if status:
        stmt = stmt.where(Invoice.status == status)
    if outstanding:
        stmt = stmt.where(Invoice.status != InvoiceStatus.paid)
    if buyer_id:
        stmt = stmt.where(Invoice.buyer_id == buyer_id)
    if order_id:
        stmt = stmt.where(Invoice.order_id == order_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = (Invoice.due_date, Invoice.id) if outstanding else (Invoice.id.desc(),)
    rows = db.execute(stmt.order_by(*order).limit(page.limit).offset(page.offset)).all()
    return {"items": [_invoice_row(*row) for row in rows], "total": total}


def get_invoice(db: Session, invoice_id: int) -> dict:
    row = db.execute(_invoice_stmt().where(Invoice.id == invoice_id)).first()
    if not row:
        raise NotFound(f"Invoice {invoice_id} not found")
    inv = row[0]
    buyer = db.get(Buyer, inv.buyer_id)
    order = db.get(Order, inv.order_id)
    lines = db.execute(
        select(InvoiceLine, Roll.code, Roll.shade_band)
        .join(Roll, Roll.id == InvoiceLine.roll_id)
        .where(InvoiceLine.invoice_id == inv.id)
        .order_by(Roll.code)
    ).all()
    payments = db.scalars(
        select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.received_at)
    ).all()
    return {
        **_invoice_row(*row),
        "buyer_gstin": buyer.gstin,
        "buyer_city": buyer.city,
        "fabric": db.get(FabricType, order.fabric_type_id).name,
        "colour": order.colour,
        "vehicle_no": db.get(Dispatch, inv.dispatch_id).vehicle_no,
        "gst_pct": GST_PCT,
        "lines": [
            {
                "roll_code": code,
                "shade_band": band,
                "metres": line.metres,
                "rate_paise_per_m": line.rate_paise_per_m,
                "amount_paise": line.amount_paise,
            }
            for line, code, band in lines
        ],
        "payments": payments,
    }


# payment against one invoice; status moves only as far as the money says
def record_payment(db: Session, user: User, data) -> Payment:
    inv = db.scalar(select(Invoice).where(Invoice.id == data.invoice_id).with_for_update())
    if not inv:
        raise NotFound("Invoice not found", field="invoice_id")
    paid = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.invoice_id == inv.id)
    )
    outstanding = inv.total_paise - paid
    if outstanding <= 0:
        raise Conflict(f"{inv.code} is already fully paid", field="invoice_id")
    if data.amount_paise > outstanding:
        raise Conflict(
            f"Only Rs {Decimal(outstanding) / 100:,.2f} is outstanding on {inv.code}",
            field="amount_paise",
        )
    if data.received_on < _ist_date(inv.issued_at):
        raise Unprocessable("Payment cannot be before the invoice date", field="received_on")
    new = InvoiceStatus.paid if data.amount_paise == outstanding else InvoiceStatus.part_paid
    if new != inv.status:
        check_transition(INVOICE_TRANSITIONS, inv.status, new)
        inv.status = new
    payment = Payment(
        invoice_id=inv.id,
        amount_paise=data.amount_paise,
        received_at=datetime.combine(data.received_on, time(12), IST),
        mode=data.mode,
        ref=data.ref,
    )
    db.add(payment)
    db.flush()
    audit.record(
        db,
        user.id,
        "payment",
        "invoices",
        inv.id,
        data={"amount_paise": data.amount_paise, "status": inv.status},
    )
    db.commit()
    events.publish("orders", {"type": "payment", "id": inv.order_id})
    return payment


def list_payments(db: Session, page: Page, invoice_id: int | None = None) -> dict:
    stmt = (
        select(Payment, Invoice.code, Buyer.name)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .join(Buyer, Buyer.id == Invoice.buyer_id)
    )
    if invoice_id:
        stmt = stmt.where(Payment.invoice_id == invoice_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(Payment.received_at.desc(), Payment.id.desc())
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    items = [
        {
            **{c: getattr(p, c) for c in ("id", "invoice_id", "amount_paise", "received_at")},
            "mode": p.mode,
            "ref": p.ref,
            "invoice_code": code,
            "buyer_name": buyer,
        }
        for p, code, buyer in rows
    ]
    return {"items": items, "total": total}


# --- wages


# pure: daily workers paid per day present (half day = 0.5), piece workers per metre woven
def wage_lines(workers: list, days: dict[int, Decimal], woven: dict[int, Decimal]) -> list[dict]:
    lines = []
    for w in workers:
        d, m = days.get(w.id, ZERO), woven.get(w.id, ZERO)
        if w.wage_type == WageType.daily:
            amount = line_amount_paise(w.daily_rate_paise, d)
        else:
            amount = line_amount_paise(w.piece_rate_paise_per_m, m)
        if amount > 0:
            lines.append({"worker_id": w.id, "days": d, "metres": qty(m), "amount_paise": amount})
    return lines


def _wage_facts(db: Session, start: date, end: date) -> tuple[dict, dict]:
    days: dict[int, Decimal] = defaultdict(Decimal)
    for worker_id, status in db.execute(
        select(Attendance.worker_id, Attendance.status).where(
            Attendance.date >= start, Attendance.date <= end
        )
    ):
        days[worker_id] += DAY_FACTOR.get(status, ZERO)
    a, b = _ist_bounds(start, end)
    woven = dict(
        db.execute(
            select(ProductionLog.worker_id, func.sum(ProductionLog.qty))
            .join(WorkOrder, WorkOrder.id == ProductionLog.work_order_id)
            .where(
                WorkOrder.stage == Stage.weaving,
                ProductionLog.unit == Unit.m,
                ProductionLog.worker_id.is_not(None),
                ProductionLog.at >= a,
                ProductionLog.at < b,
            )
            .group_by(ProductionLog.worker_id)
        ).all()
    )
    return days, woven


def _fill_lines(db: Session, run: WageRun) -> None:
    days, woven = _wage_facts(db, run.period_start, run.period_end)
    workers = db.scalars(
        select(Worker).where(Worker.id.in_(set(days) | set(woven) or {0})).order_by(Worker.code)
    ).all()
    db.add_all(WageLine(wage_run_id=run.id, **line) for line in wage_lines(workers, days, woven))
    db.flush()


def _run_out(db: Session, run: WageRun, with_lines: bool = False) -> dict:
    rows = db.execute(
        select(WageLine, Worker)
        .join(Worker, Worker.id == WageLine.worker_id)
        .where(WageLine.wage_run_id == run.id)
        .order_by(Worker.code)
    ).all()
    out = {
        **{
            c: getattr(run, c) for c in ("id", "period_start", "period_end", "status", "created_at")
        },
        "workers": len(rows),
        "total_paise": sum(line.amount_paise for line, _ in rows),
    }
    if with_lines:
        out["lines"] = [
            {
                "worker_id": w.id,
                "worker_code": w.code,
                "worker_name": w.name,
                "wage_type": w.wage_type,
                "rate_paise": w.daily_rate_paise
                if w.wage_type == WageType.daily
                else w.piece_rate_paise_per_m,
                "days": line.days,
                "metres": line.metres,
                "amount_paise": line.amount_paise,
            }
            for line, w in rows
        ]
    return out


def list_wage_runs(db: Session, page: Page) -> dict:
    result = paginate(db, select(WageRun).order_by(WageRun.period_start.desc()), page)
    return {"items": [_run_out(db, r) for r in result["items"]], "total": result["total"]}


def get_wage_run(db: Session, run_id: int, lock: bool = False) -> WageRun:
    stmt = select(WageRun).where(WageRun.id == run_id)
    run = db.scalar(stmt.with_for_update() if lock else stmt)
    if not run:
        raise NotFound(f"Wage run {run_id} not found")
    return run


def wage_run_detail(db: Session, run_id: int) -> dict:
    return _run_out(db, get_wage_run(db, run_id), with_lines=True)


def create_wage_run(db: Session, user: User, start: date, end: date) -> dict:
    clash = db.scalar(
        select(WageRun).where(WageRun.period_start <= end, WageRun.period_end >= start)
    )
    if clash:
        raise Conflict(
            f"Overlaps the run for {clash.period_start} to {clash.period_end}",
            field="period_start",
        )
    run = WageRun(period_start=start, period_end=end, status=WageRunStatus.draft)
    db.add(run)
    db.flush()
    _fill_lines(db, run)
    audit.record(
        db, user.id, "create", "wage_runs", run.id, data={"from": str(start), "to": str(end)}
    )
    db.commit()
    return wage_run_detail(db, run.id)


# draft only: attendance corrections flow in by recomputing, never by typing amounts
def recompute_wage_run(db: Session, user: User, run_id: int) -> dict:
    run = get_wage_run(db, run_id, lock=True)
    if run.status != WageRunStatus.draft:
        raise Conflict(
            f"Run is {run.status}; only a draft can be recomputed", code="illegal_transition"
        )
    for line in db.scalars(select(WageLine).where(WageLine.wage_run_id == run.id)):
        db.delete(line)
    db.flush()
    _fill_lines(db, run)
    audit.record(db, user.id, "recompute", "wage_runs", run.id)
    db.commit()
    return wage_run_detail(db, run.id)


def set_wage_run_status(db: Session, user: User, run_id: int, new: WageRunStatus) -> dict:
    run = get_wage_run(db, run_id, lock=True)
    check_transition(WAGE_RUN_TRANSITIONS, run.status, new)
    run.status = new
    audit.record(db, user.id, f"wage_run_{new}", "wage_runs", run.id)
    db.commit()
    return wage_run_detail(db, run.id)


# --- expenses


def create_expense(db: Session, user: User, data) -> Expense:
    row = Expense(**data.model_dump())
    db.add(row)
    db.flush()
    audit.record(db, user.id, "create", "expenses", row.id, data=data.model_dump(mode="json"))
    db.commit()
    return row


def list_expenses(db: Session, page: Page, month: str | None = None) -> dict:
    stmt = select(Expense).order_by(Expense.date.desc(), Expense.id.desc())
    if month:
        first, last = _month_dates(month)
        stmt = stmt.where(Expense.date >= first, Expense.date <= last)
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
        due_date=_ist_date(dispatch.confirmed_at) + timedelta(days=DUE_DAYS),
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


def _yarn_cost(db: Session, wo_ids: list[int]) -> list[dict]:
    rows = db.execute(
        select(StockMove.reason, StockMove.qty, YarnBatch)
        .join(YarnBatch, YarnBatch.id == StockMove.yarn_batch_id)
        .where(
            StockMove.item_kind == ItemKind.yarn,
            StockMove.ref_type == "work_order",
            StockMove.ref_id.in_(wo_ids or [0]),
            StockMove.reason.in_([MoveReason.issue, MoveReason.return_]),
        )
    ).all()
    kg: dict[int, Decimal] = defaultdict(Decimal)
    batches = {}
    for reason, q, batch in rows:
        kg[batch.id] += q if reason == MoveReason.issue else -q
        batches[batch.id] = batch
    # oldest receipt first: the order the cost layers were laid down
    return [
        {
            "label": batches[b].code,
            "detail": f"{qty(kg[b])} kg x Rs {Decimal(batches[b].unit_cost_paise_per_kg) / 100:.2f}"
            f"/kg (lot {batches[b].supplier_lot or '-'})",
            "amount_paise": line_amount_paise(batches[b].unit_cost_paise_per_kg, kg[b]),
        }
        for b in sorted(kg)
        if kg[b] > 0
    ]


def _shift_hours(shift: Shift) -> Decimal:
    minutes = (shift.end_time.hour * 60 + shift.end_time.minute) - (
        shift.start_time.hour * 60 + shift.start_time.minute
    )
    return Decimal(minutes % 1440) / 60


def _overlap(a1: datetime, b1: datetime, a2: datetime, b2: datetime) -> Decimal:
    a, b = max(a1, a2), min(b1, b2)
    return _hours(a, b) if b > a else ZERO


# yarn (FIFO GRN cost) + labour + machine hours + rework/reject cost, vs invoiced revenue
def order_cost(db: Session, order_id: int) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    wo_ids = list(db.scalars(select(WorkOrder.id).where(WorkOrder.order_id == order.id)))

    yarn = _yarn_cost(db, wo_ids)

    machine_ids = list(
        db.scalars(
            select(MachineEvent.machine_id)
            .where(MachineEvent.work_order_id.in_(wo_ids or [0]))
            .distinct()
        )
    )
    beginning = datetime(2000, 1, 1, tzinfo=UTC)
    running = [
        s
        for s in machine_spans(db, machine_ids, beginning, datetime.now(UTC))
        if s.status == MachineStatus.running and s.work_order_id in wo_ids
    ]
    machines = {
        m.id: m for m in db.scalars(select(Machine).where(Machine.id.in_(machine_ids or [0])))
    }
    hours: dict[int, Decimal] = defaultdict(Decimal)
    for s in running:
        hours[s.machine_id] += _hours(s.start, s.end)
    machine = [
        {
            "label": machines[m].code,
            "detail": f"{qty(h)} h x Rs {Decimal(machines[m].hourly_cost_paise) / 100:.2f}/h",
            "amount_paise": line_amount_paise(machines[m].hourly_cost_paise, h),
        }
        for m, h in sorted(hours.items())
    ]

    labour = []
    piece = db.execute(
        select(Worker, func.sum(ProductionLog.qty))
        .join(ProductionLog, ProductionLog.worker_id == Worker.id)
        .join(WorkOrder, WorkOrder.id == ProductionLog.work_order_id)
        .where(
            ProductionLog.work_order_id.in_(wo_ids or [0]),
            WorkOrder.stage == Stage.weaving,
            Worker.wage_type == WageType.piece,
        )
        .group_by(Worker.id)
    ).all()
    for w, metres in piece:
        labour.append(
            {
                "label": f"{w.code} {w.name}",
                "detail": f"{qty(metres)} m woven x {_rs(w.piece_rate_paise_per_m)}/m",
                "amount_paise": line_amount_paise(w.piece_rate_paise_per_m, metres),
            }
        )
    crew = db.execute(
        select(CrewAssignment, Worker, Shift)
        .join(Worker, Worker.id == CrewAssignment.worker_id)
        .join(Shift, Shift.id == CrewAssignment.shift_id)
        .where(
            CrewAssignment.machine_id.in_(machine_ids or [0]), Worker.wage_type == WageType.daily
        )
    ).all()
    daily: dict[int, list] = {}
    for c, w, shift in crew:
        end = c.to_at or datetime.now(UTC)
        h = sum(
            (
                _overlap(c.from_at, end, s.start, s.end)
                for s in running
                if s.machine_id == c.machine_id
            ),
            ZERO,
        )
        if h > 0:
            share = min(h / _shift_hours(shift), Decimal(1))
            entry = daily.setdefault(w.id, [w, ZERO, ZERO])
            entry[1] += h
            entry[2] += Decimal(w.daily_rate_paise) * share
    for w, h, amount in daily.values():
        labour.append(
            {
                "label": f"{w.code} {w.name}",
                "detail": f"{qty(h)} h of shifts on this order's machines, day rate "
                f"Rs {Decimal(w.daily_rate_paise) / 100:.2f}",
                "amount_paise": int(amount.quantize(Decimal(1), ROUND_HALF_UP)),
            }
        )

    by_status = dict(
        db.execute(
            select(Roll.status, func.sum(Roll.length_m))
            .where(Roll.order_id == order.id)
            .group_by(Roll.status)
        ).all()
    )
    produced = qty(sum(by_status.values(), ZERO))
    passed = qty(
        by_status.get(RollStatus.passed, ZERO) + by_status.get(RollStatus.dispatched, ZERO)
    )
    rejected = qty(by_status.get(RollStatus.rejected, ZERO))
    passed_rolls = db.scalar(
        select(func.count()).where(
            Roll.order_id == order.id,
            Roll.status.in_([RollStatus.passed, RollStatus.dispatched]),
        )
    )
    totals = {
        k: sum(x["amount_paise"] for x in v)
        for k, v in (("yarn", yarn), ("machine", machine), ("labour", labour))
    }
    total = sum(totals.values())
    invoiced = db.scalar(
        select(func.coalesce(func.sum(Invoice.subtotal_paise), 0)).where(
            Invoice.order_id == order.id
        )
    )

    def per(amount: int, base: Decimal | int) -> int | None:
        return (
            int((Decimal(amount) / Decimal(base)).quantize(Decimal(1), ROUND_HALF_UP))
            if base
            else None
        )

    return {
        "order_id": order.id,
        "order_code": order.code,
        "yarn_paise": totals["yarn"],
        "machine_paise": totals["machine"],
        "labour_paise": totals["labour"],
        "total_paise": total,
        "yarn": yarn,
        "machine": machine,
        "labour": labour,
        "produced_m": produced,
        "passed_m": passed,
        "rejected_m": rejected,
        "passed_rolls": passed_rolls,
        "reject_share_paise": per(total * rejected, produced) or 0,
        "cost_per_m_paise": per(total, passed),
        "cost_per_roll_paise": per(total, passed_rolls),
        "invoiced_paise": invoiced,
        "margin_paise": invoiced - total if invoiced else None,
        "rules": COST_RULES,
    }


# --- every order worked or billed in a month, with its cost to date (scene 7)


def order_costs(db: Session, month: str) -> list[dict]:
    first, last = _month_dates(month)
    a, b = _ist_bounds(first, last)
    billed = select(Invoice.order_id).where(Invoice.issued_at >= a, Invoice.issued_at < b)
    worked = (
        select(WorkOrder.order_id)
        .join(ProductionLog, ProductionLog.work_order_id == WorkOrder.id)
        .where(ProductionLog.at >= a, ProductionLog.at < b)
    )
    orders = db.execute(
        select(Order, Buyer.name)
        .join(Buyer, Buyer.id == Order.buyer_id)
        .where(Order.id.in_(billed.union(worked).scalar_subquery()))
        .order_by(Order.code)
    ).all()
    rows = []
    for order, buyer in orders:
        c = order_cost(db, order.id)
        rows.append(
            {
                "order_id": order.id,
                "order_code": order.code,
                "buyer_name": buyer,
                "status": order.status,
                "qty_m": order.qty_m,
                "passed_m": c["passed_m"],
                **{k: c[k] for k in ("yarn_paise", "labour_paise", "machine_paise")},
                **{k: c[k] for k in ("total_paise", "invoiced_paise", "margin_paise")},
                "cost_per_m_paise": c["cost_per_m_paise"],
            }
        )
    return rows


# --- machine production (R22) and the month (R23)


def machine_production(db: Session, month: str) -> list[dict]:
    first, last = _month_dates(month)
    a, b = _ist_bounds(first, last)
    machines = db.scalars(
        select(Machine).where(Machine.active.is_(True)).order_by(Machine.code)
    ).all()
    ist_day = func.date(func.timezone("Asia/Kolkata", ProductionLog.at))
    per_day = db.execute(
        select(ProductionLog.machine_id, ist_day, func.sum(ProductionLog.qty))
        .where(ProductionLog.at >= a, ProductionLog.at < b)
        .group_by(ProductionLog.machine_id, ist_day)
        .order_by(ist_day)
    ).all()
    days: dict[int, list] = defaultdict(list)
    for machine_id, day, total in per_day:
        days[machine_id].append({"day": day, "qty": qty(total)})
    hours: dict[int, dict] = defaultdict(lambda: defaultdict(Decimal))
    for s in machine_spans(db, [m.id for m in machines], a, b):
        hours[s.machine_id][s.status] += _hours(s.start, s.end)
    return [
        {
            "machine_id": m.id,
            "code": m.code,
            "name": m.name,
            "unit": m.output_unit,
            "month_qty": qty(sum((d["qty"] for d in days[m.id]), ZERO)),
            "days": days[m.id],
            "hours": {st.value: hours[m.id][st].quantize(Decimal("0.1")) for st in MachineStatus},
        }
        for m in machines
    ]


def month_view(db: Session, month: str) -> dict:
    first, last = _month_dates(month)
    a, b = _ist_bounds(first, last)
    total, subtotal = db.execute(
        select(
            func.coalesce(func.sum(Invoice.total_paise), 0),
            func.coalesce(func.sum(Invoice.subtotal_paise), 0),
        ).where(Invoice.issued_at >= a, Invoice.issued_at < b)
    ).one()
    received = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(
            Payment.received_at >= a, Payment.received_at < b
        )
    )
    bills = db.scalar(
        select(func.coalesce(func.sum(Receipt.bill_amount_paise), 0)).where(
            Receipt.status == ReceiptStatus.confirmed,
            Receipt.confirmed_at >= a,
            Receipt.confirmed_at < b,
        )
    )

    def wages(statuses: list[WageRunStatus]) -> int:
        return db.scalar(
            select(func.coalesce(func.sum(WageLine.amount_paise), 0))
            .join(WageRun, WageRun.id == WageLine.wage_run_id)
            .where(
                WageRun.status.in_(statuses),
                WageRun.period_end >= first,
                WageRun.period_end <= last,
            )
        )

    accrued = wages([WageRunStatus.final, WageRunStatus.paid])
    paid_wages = wages([WageRunStatus.paid])
    expenses = db.scalar(
        select(func.coalesce(func.sum(Expense.amount_paise), 0)).where(
            Expense.date >= first, Expense.date <= last
        )
    )
    return {
        "month": month,
        "invoiced_paise": total,
        "invoiced_ex_gst_paise": subtotal,
        "received_paise": received,
        "yarn_bills_paise": bills,
        "wages_accrued_paise": accrued,
        "wages_paid_paise": paid_wages,
        "expenses_paise": expenses,
        "result_invoiced_paise": subtotal - bills - accrued - expenses,
        "result_cash_paise": received - bills - paid_wages - expenses,
        "notes": [
            "Invoiced basis: sales billed this month before GST, minus yarn bills, wages for "
            "runs ending this month (final or paid) and expenses.",
            "Cash basis: money received this month (includes GST collected), minus yarn bills, "
            "wage runs marked paid and expenses.",
            "Yarn bills count when the receipt is confirmed; supplier payments are not "
            "tracked yet.",
            "Wage runs are dated by their period end.",
        ],
    }


# the rows behind one number on the month page
def month_records(db: Session, month: str, kind: str) -> list[dict]:
    first, last = _month_dates(month)
    a, b = _ist_bounds(first, last)
    if kind == "invoiced":
        rows = db.execute(
            select(Invoice, Buyer.name)
            .join(Buyer, Buyer.id == Invoice.buyer_id)
            .where(Invoice.issued_at >= a, Invoice.issued_at < b)
            .order_by(Invoice.issued_at)
        ).all()
        return [
            {
                "on": _ist_date(i.issued_at),
                "ref": i.code,
                "party": n,
                "amount_paise": i.total_paise,
                "link": f"/finance/invoices?open={i.id}",
            }
            for i, n in rows
        ]
    if kind == "received":
        rows = db.execute(
            select(Payment, Invoice, Buyer.name)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Buyer, Buyer.id == Invoice.buyer_id)
            .where(Payment.received_at >= a, Payment.received_at < b)
            .order_by(Payment.received_at)
        ).all()
        return [
            {
                "on": _ist_date(p.received_at),
                "ref": f"{i.code} {p.mode} {p.ref or ''}".strip(),
                "party": n,
                "amount_paise": p.amount_paise,
                "link": f"/finance/invoices?open={i.id}",
            }
            for p, i, n in rows
        ]
    if kind == "yarn_bills":
        rows = db.execute(
            select(Receipt, Supplier.name)
            .join(Supplier, Supplier.id == Receipt.supplier_id)
            .where(
                Receipt.status == ReceiptStatus.confirmed,
                Receipt.confirmed_at >= a,
                Receipt.confirmed_at < b,
            )
            .order_by(Receipt.confirmed_at)
        ).all()
        return [
            {
                "on": _ist_date(r.confirmed_at),
                "ref": f"{r.code} bill {r.bill_no or '-'}",
                "party": n,
                "amount_paise": r.bill_amount_paise,
                "link": None,
            }
            for r, n in rows
        ]
    if kind == "wages":
        runs = db.scalars(
            select(WageRun)
            .where(
                WageRun.period_end >= first,
                WageRun.period_end <= last,
                WageRun.status != WageRunStatus.draft,
            )
            .order_by(WageRun.period_end)
        ).all()
        return [
            {
                "on": r.period_end,
                "ref": f"Wage run {r.period_start} to {r.period_end} ({r.status})",
                "party": f"{x['workers']} workers",
                "amount_paise": x["total_paise"],
                "link": f"/finance/wages?open={r.id}",
            }
            for r in runs
            for x in [_run_out(db, r)]
        ]
    rows = db.scalars(
        select(Expense).where(Expense.date >= first, Expense.date <= last).order_by(Expense.date)
    ).all()
    return [
        {
            "on": e.date,
            "ref": str(e.category),
            "party": e.note or "-",
            "amount_paise": e.amount_paise,
            "link": None,
        }
        for e in rows
    ]
