from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.core.enums import Source, Stage, Unit
from app.modules.auth.models import Role
from app.modules.dispatch.models import Dispatch, DispatchStatus
from app.modules.finance import service
from app.modules.finance.models import Expense, ExpenseCategory, Invoice, InvoiceStatus, WageRun
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


def invoice_for(db, order, subtotal, days_ago=2):
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
    for length, status in ((150, RollStatus.passed), (50, RollStatus.rejected)):
        mill.roll(wo, length, status=status)
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
    invoice_for(db, o, 150 * 18500)  # Rs 27,750 before GST

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
    rows = client_as(Role.owner).get(f"/api/finance/machine-production?month={start:%Y-%m}").json()
    loom = next(r for r in rows if r["code"] == "LM-T1")
    assert Decimal(loom["month_qty"]) == 95
    assert Decimal(loom["hours"]["running"]) == 6 and Decimal(loom["hours"]["breakdown"]) == 2
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
