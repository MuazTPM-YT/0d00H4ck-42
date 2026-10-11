from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.core.dates import mill_today
from app.core.enums import Source, Stage, Unit
from app.modules.auth.models import Role
from app.modules.dispatch.models import Dispatch, DispatchStatus
from app.modules.finance import service
from app.modules.finance.models import (
    Expense,
    ExpenseCategory,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    WageRun,
    WageRunStatus,
)
from app.modules.inventory.models import (
    BatchStatus,
    ItemKind,
    MoveReason,
    Receipt,
    ReceiptStatus,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import Supplier, WageType, Worker, YarnItem
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.quality.models import RollStatus
from app.modules.workforce.models import Attendance, AttendanceStatus, CrewAssignment
from tests.mill import NOW, Mill

IST = service.IST


@pytest.fixture
def mill(db):
    return Mill(db)


def invoice_for(db, order, subtotal, days_ago=2, rolls=()):
    at = NOW - timedelta(days=days_ago)
    d = Dispatch(
        code=f"DN-F{order.id}",
        order_id=order.id,
        buyer_id=order.buyer_id,
        vehicle_no="KA01AB1234",
        status=DispatchStatus.confirmed,
        confirmed_at=at,
    )
    db.add(d)
    db.flush()
    tax = service.gst_paise(subtotal)
    inv = Invoice(
        code=f"INV-F{order.id}",
        dispatch_id=d.id,
        buyer_id=order.buyer_id,
        order_id=order.id,
        subtotal_paise=subtotal,
        tax_paise=tax,
        total_paise=subtotal + tax,
        issued_at=at,
        due_date=at.date() + timedelta(days=30),
    )
    db.add(inv)
    db.flush()
    db.add_all(
        InvoiceLine(
            invoice_id=inv.id,
            roll_id=r.id,
            metres=r.length_m,
            rate_paise_per_m=order.rate_paise_per_m,
            amount_paise=int(r.length_m * order.rate_paise_per_m),
        )
        for r in rolls
    )
    db.commit()
    return inv


def daily_worker(db, code="W-D1", rate=60000):
    w = Worker(code=code, name=f"Helper {code}", wage_type=WageType.daily, daily_rate_paise=rate)
    db.add(w)
    db.flush()
    return w


# --- order cost on a small example worked out by hand


def test_order_cost_hand_calculated(db, mill):
    o = mill.order(200, rate=18500)
    wo = mill.work_order(o)
    sup = Supplier(code="SUPF", name="Yarn Co")
    item = YarnItem(fibre="Cotton", count="Ne 40/1", colour="Navy")
    db.add_all([sup, item])
    db.flush()
    rc = Receipt(code="RC-F1", supplier_id=sup.id, status=ReceiptStatus.confirmed, confirmed_at=NOW)
    db.add(rc)
    db.flush()
    b1, b2 = (
        YarnBatch(
            code=f"YB-F{i}",
            supplier_id=sup.id,
            yarn_item_id=item.id,
            receipt_id=rc.id,
            received_kg=Decimal(100),
            unit_cost_paise_per_kg=cost,
            status=BatchStatus.approved,
            supplier_lot=f"L{i}",
        )
        for i, cost in ((1, 25000), (2, 30000))
    )
    db.add_all([b1, b2])
    db.flush()
    for batch, kg, reason, frm, to in [
        (b1, 20, MoveReason.issue, "YS-01", "WIP"),  # 20 kg x Rs 250 = Rs 5,000
        (b2, 10, MoveReason.issue, "YS-01", "WIP"),  # 10 kg x Rs 300
        (b2, 2, MoveReason.return_, "WIP", "YS-01"),  # 2 kg back: 8 kg x Rs 300 = Rs 2,400
        (b2, 8, MoveReason.consume, "WIP", "PROD"),  # consumption is not a second charge
    ]:
        db.add(
            StockMove(
                item_kind=ItemKind.yarn,
                yarn_batch_id=batch.id,
                qty=Decimal(kg),
                unit=Unit.kg,
                from_location_id=mill.loc[frm].id,
                to_location_id=mill.loc[to].id,
                reason=reason,
                ref_type="work_order",
                ref_id=wo.id,
            )
        )
    # loom ran 10 h on this work order: 10 h x Rs 300 = Rs 3,000
    start = NOW - timedelta(days=3)
    db.add_all(
        [
            MachineEvent(
                machine_id=mill.loom.id, at=start, status=MachineStatus.running, work_order_id=wo.id
            ),
            MachineEvent(
                machine_id=mill.loom.id, at=start + timedelta(hours=10), status=MachineStatus.idle
            ),
        ]
    )
    # helper on the loom for an 8 h shift, 4 h of it while the order ran: Rs 600 x 4/8 = Rs 300
    helper = daily_worker(db)
    db.add(
        CrewAssignment(
            date=start.date(),
            shift_id=mill.shift.id,
            worker_id=helper.id,
            machine_id=mill.loom.id,
            from_at=start + timedelta(hours=6),
            to_at=start + timedelta(hours=14),
        )
    )
    # rolls: 150 m passed, 50 m rejected; weaver paid 200 m x Rs 4 = Rs 800
    rolls = []
    for length, status in ((150, RollStatus.passed), (50, RollStatus.rejected)):
        rolls.append(mill.roll(wo, length, status=status))
        db.add(
            ProductionLog(
                work_order_id=wo.id,
                machine_id=mill.loom.id,
                shift_id=mill.shift.id,
                worker_id=mill.weaver.id,
                qty=Decimal(length),
                unit=Unit.m,
            )
        )
    db.flush()
    invoice_for(db, o, 150 * 18500, rolls=rolls[:1])  # Rs 27,750 before GST

    c = service.order_cost(db, o.id)
    assert (c["yarn_paise"], c["machine_paise"], c["labour_paise"]) == (740_000, 300_000, 110_000)
    assert c["total_paise"] == 1_150_000
    assert c["passed_m"] == 150 and c["rejected_m"] == 50 and c["passed_rolls"] == 1
    assert c["cost_per_m_paise"] == 7_667  # 11,500 / 150 = 76.666...
    assert c["reject_share_paise"] == 287_500  # a quarter of the metres were rejected
    assert c["margin_paise"] == 2_775_000 - 1_150_000
    assert [x["label"] for x in c["yarn"]] == ["YB-F1", "YB-F2"]


def test_order_cost_is_accounts_only(client_as, mill, db):
    o = mill.order()
    db.commit()
    assert client_as(Role.store).get(f"/api/finance/orders/{o.id}/cost").status_code == 403
    res = client_as(Role.accounts).get(f"/api/finance/orders/{o.id}/cost")
    assert res.status_code == 200 and res.json()["rules"]


# --- payments drive invoice status


def pay(client, inv, amount, on=None, mode="upi"):
    return client.post(
        "/api/finance/payments",
        json={
            "invoice_id": inv.id,
            "amount_paise": amount,
            "mode": mode,
            "received_on": (on or date.today()).isoformat(),
        },
    )


def test_payment_status_issued_part_paid_paid(client_as, db, mill):
    inv = invoice_for(db, mill.order(), 100_000)  # total 105,000 with GST
    acc = client_as(Role.accounts)
    assert pay(acc, inv, 50_000).status_code == 201
    db.refresh(inv)
    assert inv.status == InvoiceStatus.part_paid

    over = pay(acc, inv, 60_000)
    assert over.status_code == 409 and over.json()["error"]["field"] == "amount_paise"

    assert pay(acc, inv, 55_000).status_code == 201
    db.refresh(inv)
    assert inv.status == InvoiceStatus.paid
    assert pay(acc, inv, 1).json()["error"]["field"] == "invoice_id"

    row = acc.get(f"/api/finance/invoices/{inv.id}").json()
    assert row["paid_paise"] == 105_000 and row["outstanding_paise"] == 0
    assert len(row["payments"]) == 2


def test_payment_rejects_bad_input(client_as, db, mill):
    inv = invoice_for(db, mill.order(), 100_000)
    acc = client_as(Role.accounts)
    future = pay(acc, inv, 1000, on=date.today() + timedelta(days=1))
    assert future.status_code == 422 and future.json()["error"]["field"] == "received_on"
    early = pay(acc, inv, 1000, on=date.today() - timedelta(days=30))
    assert early.status_code == 422 and early.json()["error"]["field"] == "received_on"
    assert pay(acc, inv, 0).json()["error"]["field"] == "amount_paise"
    assert pay(acc, inv, 1000, mode="bitcoin").status_code == 422


def test_only_accounts_record_payments(client_as, db, mill):
    inv = invoice_for(db, mill.order(), 100_000)
    assert pay(client_as(Role.dispatch), inv, 1000).status_code == 403


# --- wage run on a small example worked out by hand


def test_wage_run_hand_calculated(client_as, db, mill):
    start, end = date.today() - timedelta(days=9), date.today() - timedelta(days=1)
    helper = daily_worker(db, rate=65000)
    for i, status in enumerate(
        [AttendanceStatus.present] * 3 + [AttendanceStatus.half_day, AttendanceStatus.absent]
    ):
        db.add(
            Attendance(
                date=start + timedelta(days=i),
                shift_id=mill.shift.id,
                worker_id=helper.id,
                status=status,
            )
        )
    db.add(
        Attendance(
            date=start - timedelta(days=1),
            shift_id=mill.shift.id,
            worker_id=helper.id,
            status=AttendanceStatus.present,
        )
    )  # before the period: not paid here
    o = mill.order()
    weave = mill.work_order(o)
    dye = WorkOrder(
        code="WO-FD",
        order_id=o.id,
        stage=Stage.dyeing,
        seq=2,
        planned_qty=Decimal(300),
        unit=Unit.m,
        status=WorkOrderStatus.waiting,
    )
    db.add(dye)
    db.flush()
    in_period = datetime.combine(start + timedelta(days=2), time(10), IST)
    for wo, metres, at in [
        (weave, "120.5", in_period),
        (weave, "80", in_period + timedelta(days=1)),
        (weave, "999", datetime.combine(end + timedelta(days=1), time(1), IST)),  # after period
        (dye, "500", in_period),  # dyeing metres are not weaving piece work
    ]:
        db.add(
            ProductionLog(
                work_order_id=wo.id,
                machine_id=mill.loom.id,
                shift_id=mill.shift.id,
                worker_id=mill.weaver.id,
                qty=Decimal(metres),
                unit=Unit.m,
                at=at,
                source=Source.machine,
            )
        )
    db.commit()

    acc = client_as(Role.accounts)
    res = acc.post(
        "/api/finance/wage-runs", json={"period_start": str(start), "period_end": str(end)}
    )
    assert res.status_code == 201, res.text
    run = res.json()
    lines = {line["worker_code"]: line for line in run["lines"]}
    assert Decimal(lines["W-D1"]["days"]) == Decimal("3.5")
    assert lines["W-D1"]["amount_paise"] == 227_500  # 3.5 x Rs 650
    assert Decimal(lines["W-T9"]["metres"]) == Decimal("200.5")
    assert lines["W-T9"]["amount_paise"] == 80_200  # 200.5 m x Rs 4
    assert run["total_paise"] == 307_700 and run["status"] == "draft"

    clash = acc.post(
        "/api/finance/wage-runs", json={"period_start": str(end), "period_end": str(end)}
    )
    assert clash.status_code == 409 and clash.json()["error"]["field"] == "period_start"

    rid = run["id"]
    assert (
        acc.post(f"/api/finance/wage-runs/{rid}/pay").json()["error"]["code"]
        == "illegal_transition"
    )
    assert acc.post(f"/api/finance/wage-runs/{rid}/finalize").json()["status"] == "final"
    assert acc.post(f"/api/finance/wage-runs/{rid}/recompute").status_code == 409
    assert acc.post(f"/api/finance/wage-runs/{rid}/pay").json()["status"] == "paid"
    assert db.get(WageRun, rid).status == "paid"


def test_wage_period_validated(client_as):
    acc = client_as(Role.accounts)
    today = date.today()
    back = acc.post(
        "/api/finance/wage-runs",
        json={"period_start": str(today), "period_end": str(today - timedelta(days=1))},
    )
    assert back.status_code == 422 and back.json()["error"]["field"] == "period_end"
    ahead = acc.post(
        "/api/finance/wage-runs",
        json={"period_start": str(today), "period_end": str(today + timedelta(days=5))},
    )
    assert ahead.status_code == 422


def test_wage_lines_pure():
    daily = Worker(id=1, wage_type=WageType.daily, daily_rate_paise=65000)
    piece = Worker(id=2, wage_type=WageType.piece, piece_rate_paise_per_m=400)
    idle = Worker(id=3, wage_type=WageType.daily, daily_rate_paise=65000)
    lines = service.wage_lines([daily, piece, idle], {1: Decimal("0.5")}, {2: Decimal("10.25")})
    assert [(x["worker_id"], x["amount_paise"]) for x in lines] == [(1, 32_500), (2, 4_100)]


# --- month view: both bases, and every number drills down to rows that add up to it


def test_month_view_and_drilldown(client_as, db, mill):
    inv = invoice_for(db, mill.order(), 200_000, days_ago=0)
    db.add(
        Expense(
            date=date.today(), category=ExpenseCategory.power, amount_paise=30_000, note="Power"
        )
    )
    db.commit()
    acc = client_as(Role.accounts)
    assert pay(acc, inv, 100_000).status_code == 201
    month = datetime.now(IST).strftime("%Y-%m")
    view = acc.get(f"/api/finance/month?month={month}").json()
    assert view["invoiced_ex_gst_paise"] == 200_000 and view["invoiced_paise"] == 210_000
    assert view["received_paise"] == 100_000 and view["expenses_paise"] == 30_000
    assert view["result_invoiced_paise"] == 200_000 - 30_000
    assert view["result_cash_paise"] == 100_000 - 30_000
    for kind, key in [
        ("invoiced", "invoiced_paise"),
        ("received", "received_paise"),
        ("expenses", "expenses_paise"),
    ]:
        rows = acc.get(f"/api/finance/month/records?month={month}&kind={kind}").json()
        assert sum(r["amount_paise"] for r in rows) == view[key], kind
    assert acc.get("/api/finance/month?month=2026-13").status_code == 422


# collected = payments on this month's own invoices, not last month's money arriving now;
# the result says when no wage run covers the month
def test_month_collected_is_on_its_own_invoices(client_as, db, mill):
    today = datetime.now(IST).date()
    old = invoice_for(db, mill.order(), 300_000, days_ago=today.day + 1)  # last month
    new = invoice_for(db, mill.order(), 200_000, days_ago=0)
    db.commit()
    acc = client_as(Role.accounts)
    assert pay(acc, old, 315_000).status_code == 201
    assert pay(acc, new, 50_000).status_code == 201
    month = today.strftime("%Y-%m")
    view = acc.get(f"/api/finance/month?month={month}").json()
    assert view["received_paise"] == 365_000
    assert view["collected_of_invoiced_paise"] == 50_000
    assert view["wage_runs"] == 0
    first = today.replace(day=1)
    db.add(WageRun(period_start=first, period_end=first, status=WageRunStatus.final))
    db.commit()
    assert acc.get(f"/api/finance/month?month={month}").json()["wage_runs"] == 1


# yarn rejected back to the supplier is not a cost of the month, in the total or the rows
def test_yarn_sent_back_is_not_a_yarn_bill(client_as, db):
    from app.modules.inventory.models import BatchStatus, Receipt, ReceiptStatus, YarnBatch
    from tests.inventory_helpers import make_item, make_supplier

    sup, item = make_supplier(db), make_item(db, "Ne 40/1", "Raw White")
    receipt = Receipt(
        code="RC-TB1",
        supplier_id=sup.id,
        status=ReceiptStatus.confirmed,
        confirmed_at=datetime.now(IST),
        bill_amount_paise=4_275_000,  # 150 kg x Rs 285
    )
    db.add(receipt)
    db.flush()
    for kg, status in ((100, BatchStatus.approved), (50, BatchStatus.rejected)):
        db.add(
            YarnBatch(
                code=f"YB-TB{kg}",
                yarn_item_id=item.id,
                supplier_id=sup.id,
                receipt_id=receipt.id,
                received_kg=Decimal(kg),
                unit_cost_paise_per_kg=28_500,
                status=status,
            )
        )
    db.commit()
    acc = client_as(Role.accounts)
    month = datetime.now(IST).strftime("%Y-%m")
    view = acc.get(f"/api/finance/month?month={month}").json()
    assert view["yarn_bills_paise"] == 2_850_000  # the 100 kg kept
    rows = acc.get(f"/api/finance/month/records?month={month}&kind=yarn_bills").json()
    assert sum(r["amount_paise"] for r in rows) == view["yarn_bills_paise"]


def test_expense_validation(client_as):
    acc = client_as(Role.accounts)
    ok = acc.post(
        "/api/finance/expenses",
        json={"date": str(date.today()), "category": "power", "amount_paise": 5000},
    )
    assert ok.status_code == 201
    neg = acc.post(
        "/api/finance/expenses",
        json={"date": str(date.today()), "category": "power", "amount_paise": -5},
    )
    assert neg.status_code == 422 and neg.json()["error"]["field"] == "amount_paise"


def test_machine_production_counts_metres_and_hours(client_as, db, mill):
    start = datetime.combine(date.today() - timedelta(days=1), time(8), IST)
    if start.month != datetime.now(IST).month:
        pytest.skip("first day of month: yesterday is in the previous month")
    o = mill.order()
    wo = mill.work_order(o)
    db.add_all(
        [
            MachineEvent(
                machine_id=mill.loom.id, at=start, status=MachineStatus.running, work_order_id=wo.id
            ),
            MachineEvent(
                machine_id=mill.loom.id,
                at=start + timedelta(hours=6),
                status=MachineStatus.breakdown,
                reason="Belt",
            ),
            MachineEvent(
                machine_id=mill.loom.id, at=start + timedelta(hours=8), status=MachineStatus.idle
            ),
            ProductionLog(
                work_order_id=wo.id,
                machine_id=mill.loom.id,
                shift_id=mill.shift.id,
                qty=Decimal(95),
                unit=Unit.m,
                at=start + timedelta(hours=2),
            ),
        ]
    )
    db.commit()
    rework = mill.work_order(o, seq=2)
    rework.roll_id = mill.roll(wo, 40, status=RollStatus.rework).id
    db.add(
        ProductionLog(
            work_order_id=rework.id,
            machine_id=mill.loom.id,
            shift_id=mill.shift.id,
            qty=Decimal(40),
            unit=Unit.m,
            at=start + timedelta(hours=3),
        )
    )
    db.commit()
    rows = client_as(Role.owner).get(f"/api/finance/machine-production?month={start:%Y-%m}").json()
    loom = next(r for r in rows if r["code"] == "LM-T1")
    assert Decimal(loom["month_qty"]) == 95  # rework redoes metres already counted
    assert loom["type"] == "weaving"
    assert Decimal(loom["hours"]["running"]) == 6 and Decimal(loom["hours"]["breakdown"]) == 2
    # before its first report the loom was off, as the machine timeline says
    month_start = datetime.combine(start.date().replace(day=1), time(0), IST)
    assert Decimal(loom["hours"]["off"]) == Decimal((start - month_start).total_seconds() / 3600)
    assert loom["days"] == [{"day": str(start.date()), "qty": "95.000"}]


def test_finance_roles(client_as):
    assert client_as(Role.qc).get("/api/finance/invoices").status_code == 403


# scene 7: every order billed in the month, with cost to date that matches order_cost
def test_order_costs_lists_billed_orders_with_their_cost(client_as, db, mill):
    billed = mill.order()
    invoice_for(db, billed, 150_000, days_ago=0)
    quiet = mill.order()
    db.commit()
    month = datetime.now(IST).strftime("%Y-%m")
    acc = client_as(Role.accounts)
    rows = acc.get(f"/api/finance/order-costs?month={month}").json()
    assert [r["order_code"] for r in rows] == [billed.code]
    cost = service.order_cost(db, billed.id)
    assert rows[0]["total_paise"] == cost["total_paise"]
    assert rows[0]["invoiced_paise"] == cost["invoiced_paise"]
    assert quiet.code not in {r["order_code"] for r in rows}
    assert client_as(Role.store).get(f"/api/finance/order-costs?month={month}").status_code == 403


# --- cost stops when the work stops; margin only on what was billed


def running_since(db, mill, wo, start):
    db.add(
        MachineEvent(
            machine_id=mill.loom.id, at=start, status=MachineStatus.running, work_order_id=wo.id
        )
    )
    db.flush()


# a done job's last "running" event must not bill the loom until now
def test_machine_cost_stops_at_job_done(db, mill):
    o = mill.order(200)
    wo = mill.work_order(o)
    start = NOW - timedelta(days=4)
    running_since(db, mill, wo, start)
    wo.finished_at = start + timedelta(hours=5)
    db.flush()
    c = service.order_cost(db, o.id)
    assert c["machine_paise"] == 150_000  # 5 h x Rs 300
    assert c["cost_to_date"] is False


# done job with no finish time: stop at its last production log
def test_machine_cost_stops_at_last_log_without_finish_time(db, mill):
    o = mill.order(200)
    wo = mill.work_order(o)
    start = NOW - timedelta(days=4)
    running_since(db, mill, wo, start)
    wo.finished_at = None
    db.add(
        ProductionLog(
            work_order_id=wo.id,
            machine_id=mill.loom.id,
            shift_id=mill.shift.id,
            qty=Decimal(50),
            unit=Unit.m,
            at=start + timedelta(hours=3),
        )
    )
    db.flush()
    assert service.order_cost(db, o.id)["machine_paise"] == 90_000  # 3 h x Rs 300


# running job: cost to date, still counted up to now
def test_running_job_is_cost_to_date(db, mill):
    o = mill.order(200)
    wo = mill.work_order(o, status=WorkOrderStatus.running)
    running_since(db, mill, wo, NOW - timedelta(hours=2))
    c = service.order_cost(db, o.id)
    assert c["cost_to_date"] is True and c["cost_provisional"] is True
    assert c["machine_paise"] >= 60_000


# open crew assignment on a running job is clipped to its shift, never to now
def test_crew_labour_clipped_to_shift_window(db, mill):
    o = mill.order(200)
    wo = mill.work_order(o, status=WorkOrderStatus.running)
    day = (NOW - timedelta(days=3)).astimezone(IST).date()
    shift_start = datetime.combine(day, time(6), IST)
    running_since(db, mill, wo, shift_start)
    helper = daily_worker(db)
    db.add(
        CrewAssignment(
            date=day,
            shift_id=mill.shift.id,
            worker_id=helper.id,
            machine_id=mill.loom.id,
            from_at=shift_start,
            to_at=None,
        )
    )
    db.flush()
    labour = service.order_cost(db, o.id)["labour"]
    line = next(x for x in labour if x["label"].startswith("W-D1"))
    assert line["detail"].startswith("8.000 h")
    assert line["amount_paise"] == 60_000


# margin = invoiced - cost per metre x invoiced metres, not the whole order's cost
def test_margin_on_invoiced_metres_only(db, mill):
    o = mill.order(200, rate=18500)
    wo = mill.work_order(o)
    start = NOW - timedelta(days=4)
    running_since(db, mill, wo, start)
    wo.finished_at = start + timedelta(hours=10)  # 10 h x Rs 300 = Rs 3,000
    shipped = mill.roll(wo, 100)
    mill.roll(wo, 100)
    db.flush()
    invoice_for(db, o, 100 * 18500, rolls=[shipped])
    c = service.order_cost(db, o.id)
    assert c["total_paise"] == 300_000 and c["invoiced_m"] == 100
    assert c["margin_paise"] == 1_850_000 - 150_000  # half the passed metres billed
    assert c["cost_provisional"] is False


def test_cost_per_m_provisional_while_rolls_wait_for_qc(db, mill):
    o = mill.order(200)
    wo = mill.work_order(o)
    mill.roll(wo, 100)
    mill.roll(wo, 90, status=RollStatus.awaiting_qc)
    c = service.order_cost(db, o.id)
    assert c["cost_provisional"] is True and c["cost_to_date"] is False


# rework passes are not new weaving: no piece wage, no piece cost
def test_rework_metres_not_paid_as_piece_work(client_as, db, mill):
    o = mill.order()
    weave = mill.work_order(o)
    roll = mill.roll(weave, 60, status=RollStatus.rework)
    redo = WorkOrder(
        code="WO-FR",
        order_id=o.id,
        stage=Stage.weaving,
        seq=1,
        roll_id=roll.id,
        planned_qty=Decimal(60),
        unit=Unit.m,
        status=WorkOrderStatus.done,
    )
    db.add(redo)
    db.flush()
    at = datetime.combine(date.today() - timedelta(days=2), time(10), IST)
    for wo, metres in ((weave, "100"), (redo, "60")):
        db.add(
            ProductionLog(
                work_order_id=wo.id,
                machine_id=mill.loom.id,
                shift_id=mill.shift.id,
                worker_id=mill.weaver.id,
                qty=Decimal(metres),
                unit=Unit.m,
                at=at,
            )
        )
    db.commit()
    labour = service.order_cost(db, o.id)["labour"]
    piece = next(x for x in labour if x["label"].startswith("W-T9"))
    assert piece["amount_paise"] == 40_000  # 100 m x Rs 4
    day = str(date.today() - timedelta(days=1))
    start = str(date.today() - timedelta(days=3))
    run = client_as(Role.accounts).post(
        "/api/finance/wage-runs", json={"period_start": start, "period_end": day}
    )
    lines = {x["worker_code"]: x for x in run.json()["lines"]}
    assert Decimal(lines["W-T9"]["metres"]) == 100


# --- wage run dates, draft delete, period lock


def test_wage_run_cannot_include_today(client_as):
    today = datetime.now(IST).date()
    res = client_as(Role.accounts).post(
        "/api/finance/wage-runs",
        json={"period_start": str(today - timedelta(days=3)), "period_end": str(today)},
    )
    assert res.status_code == 422 and res.json()["error"]["field"] == "period_end"


def test_delete_draft_wage_run_only(client_as, db):
    acc = client_as(Role.accounts)
    yday = datetime.now(IST).date() - timedelta(days=1)
    body = {"period_start": str(yday - timedelta(days=5)), "period_end": str(yday)}
    rid = acc.post("/api/finance/wage-runs", json=body).json()["id"]
    assert acc.delete(f"/api/finance/wage-runs/{rid}").status_code == 204
    assert acc.get(f"/api/finance/wage-runs/{rid}").status_code == 404
    rid = acc.post("/api/finance/wage-runs", json=body).json()["id"]  # dates free again
    acc.post(f"/api/finance/wage-runs/{rid}/finalize")
    res = acc.delete(f"/api/finance/wage-runs/{rid}")
    assert res.status_code == 409 and res.json()["error"]["code"] == "illegal_transition"
    assert client_as(Role.supervisor).delete(f"/api/finance/wage-runs/{rid}").status_code == 403


def test_period_locked_by_final_or_paid_run(db):
    db.add_all(
        [
            WageRun(
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 15),
                status=WageRunStatus.draft,
            ),
            WageRun(
                period_start=date(2026, 3, 16),
                period_end=date(2026, 3, 31),
                status=WageRunStatus.final,
            ),
            WageRun(
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 15),
                status=WageRunStatus.paid,
            ),
        ]
    )
    db.flush()
    assert service.period_locked(db, date(2026, 3, 10)) is False
    assert service.period_locked(db, date(2026, 3, 16)) is True
    assert service.period_locked(db, date(2026, 4, 15)) is True
    assert service.period_locked(db, date(2026, 4, 16)) is False


# cash basis "wages paid" opens paid runs only; accrued opens final + paid
def test_month_wages_paid_drilldown_is_paid_runs_only(client_as, db):
    today = datetime.now(IST).date()
    if today.day < 3:
        pytest.skip("needs two past days in this month")
    first = today.replace(day=1)
    second = first + timedelta(days=1)
    db.add_all(
        [
            WageRun(period_start=first, period_end=first, status=WageRunStatus.final),
            WageRun(period_start=second, period_end=second, status=WageRunStatus.paid),
        ]
    )
    db.commit()
    acc = client_as(Role.accounts)
    month = today.strftime("%Y-%m")
    paid = acc.get(f"/api/finance/month/records?month={month}&kind=wages_paid")
    assert paid.status_code == 200
    assert [r["ref"].endswith("(paid)") for r in paid.json()] == [True]
    accrued = acc.get(f"/api/finance/month/records?month={month}&kind=wages").json()
    assert len(accrued) == 2


# two clerks create overlapping wage runs at the same moment: one wins, one gets the overlap 409
def test_overlapping_wage_runs_at_once_never_both_land(committed, password_hash):
    import threading

    from sqlalchemy.orm import Session

    from app.core.errors import Conflict
    from app.modules.auth.models import User

    with Session(committed) as s:
        clerk = User(name="A", email="a@t.local", role=Role.accounts, password_hash=password_hash)
        s.add(clerk)
        s.commit()
        clerk_id = clerk.id
    day = date.today() - timedelta(days=3)
    barrier = threading.Barrier(2)
    outcomes = []

    def create(end):
        with Session(committed) as s:
            barrier.wait()
            try:
                service.create_wage_run(s, s.get(User, clerk_id), day, end)
                outcomes.append("ok")
            except Conflict as e:
                outcomes.append(e.field)

    threads = [threading.Thread(target=create, args=(day + timedelta(days=i),)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok", "period_start"]


# month-end close: a past month locks; nothing dated in it changes until the owner reopens it
def test_closed_month_refuses_backdated_books(client_as, db):
    mill = Mill(db)
    db.commit()
    this_month = mill_today().replace(day=1)
    last_day = this_month - timedelta(days=1)
    month = f"{last_day:%Y-%m}"
    accounts = client_as(Role.accounts)
    closes = "/api/finance/month-closes"
    assert accounts.post(closes, json={"month": f"{this_month:%Y-%m}"}).status_code == 422
    assert accounts.post(closes, json={"month": month}).status_code == 201
    assert accounts.post(closes, json={"month": month}).status_code == 409
    assert accounts.get(closes).json() == [month]

    expense = {"date": str(last_day), "category": "power", "amount_paise": 50000}
    res = accounts.post("/api/finance/expenses", json=expense)
    assert res.status_code == 409 and res.json()["error"]["code"] == "month_closed"
    run = {"period_start": str(last_day.replace(day=1)), "period_end": str(last_day)}
    assert accounts.post("/api/finance/wage-runs", json=run).status_code == 409
    mark = {
        "date": str(last_day),
        "shift_id": mill.shift.id,
        "worker_id": mill.weaver.id,
        "status": "present",
        "reason": "Late entry",
    }
    supervisor = client_as(Role.supervisor)  # same test client, header now supervisor
    res = supervisor.put("/api/workforce/attendance", json=mark)
    assert res.status_code == 409 and res.json()["error"]["code"] == "month_closed"
    assert supervisor.post(f"{closes}/{month}/reopen", json={"reason": "x"}).status_code == 403

    owner = client_as(Role.owner)
    reopen = owner.post(f"{closes}/{month}/reopen", json={"reason": "Power bill came late"})
    assert reopen.status_code == 200 and reopen.json() == []
    assert owner.post("/api/finance/expenses", json=expense).status_code == 201
