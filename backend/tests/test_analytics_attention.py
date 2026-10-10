from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.enums import Source
from app.modules.analytics import service
from app.modules.analytics.models import Insight, Severity
from app.modules.auth.models import Role
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance.models import Invoice, WageRun, WageRunStatus
from app.modules.inventory import service as inventory
from app.modules.inventory.models import BatchStatus
from app.modules.masters.models import LocationKind, YarnItem
from app.modules.orders.models import OrderStatus
from app.modules.production.models import MachineEvent, MachineStatus, WorkOrderStatus
from app.modules.quality.models import Roll, RollEvent, RollStatus
from tests.floor import build_floor

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


def event(db, machine, status, ago, reason=None):
    db.add(
        MachineEvent(
            machine_id=machine.id,
            at=NOW - ago,
            status=status,
            reason=reason,
            source=Source.machine,
        )
    )
    db.commit()


def roll(db, floor, code, status=RollStatus.awaiting_qc, ready_ago=None, passed_ago=None):
    r = Roll(
        code=code,
        order_id=floor.shirt_order.id,
        work_order_id=floor.shirt_weave.id,
        loom_machine_id=floor.loom1.id,
        shift_id=floor.shifts[0].id,
        length_m=Decimal(60),
        status=status,
        shade_band="A" if passed_ago else None,
        passed_at=NOW - passed_ago if passed_ago else None,
        location_id=floor.loc[LocationKind.wip].id,
    )
    db.add(r)
    db.flush()
    if ready_ago:
        db.add(RollEvent(roll_id=r.id, at=NOW - ready_ago, kind="woven"))
    db.commit()
    return r


def titles(items) -> list[str]:
    return [i["title"] for i in items]


# one kind of the role's list; the same fixture also raises other real hand-offs
def of_kind(items, kind) -> list[dict]:
    return [i for i in items if i["kind"] == kind]


def test_supervisor_sees_stopped_and_long_idle_machines(db, floor):
    event(db, floor.loom1, MachineStatus.breakdown, timedelta(hours=1), "Warp beam snapped")
    event(db, floor.loom2, MachineStatus.idle, timedelta(minutes=45))
    event(db, floor.jigger, MachineStatus.idle, timedelta(minutes=10))
    items = service.attention_items(db, Role.supervisor, NOW)
    assert titles(items) == ["LM-T1 in breakdown", "LM-T2 idle"]
    assert items[0]["severity"] == Severity.critical
    assert items[0]["detail"] == "60 min: Warp beam snapped"
    assert items[0]["href"] == f"/floor?machine={floor.loom1.id}"


def test_qc_sees_rolls_waiting_over_four_hours(db, floor):
    old = roll(db, floor, "R-T1", ready_ago=timedelta(hours=5))
    roll(db, floor, "R-T2", ready_ago=timedelta(hours=1))
    items = service.attention_items(db, Role.qc, NOW)
    assert titles(items) == ["R-T1 waiting for QC"]
    assert items[0]["href"] == f"/qc/rolls/{old.id}"


def test_dispatch_sees_rolls_on_shelf_for_days(db, floor):
    roll(db, floor, "R-T3", RollStatus.passed, passed_ago=timedelta(days=4))
    roll(db, floor, "R-T4", RollStatus.passed, passed_ago=timedelta(days=1))
    assert titles(service.attention_items(db, Role.dispatch, NOW)) == ["R-T3 on shelf"]


# idle with nothing to run is not a problem; idle with a job lined up is
def test_idle_machine_alerts_only_when_work_waits_for_it(db, floor):
    floor.dyed_order.status = OrderStatus.cancelled
    db.commit()
    event(db, floor.jigger, MachineStatus.idle, timedelta(minutes=45))
    assert titles(service.attention_items(db, Role.supervisor, NOW)) == []

    floor.dyed_dye.status, floor.dyed_dye.machine_id = WorkOrderStatus.queued, floor.jigger.id
    db.commit()
    items = service.attention_items(db, Role.supervisor, NOW)
    assert titles(items) == ["DYE-T1 idle"]
    assert items[0]["href"] == f"/floor?machine={floor.jigger.id}"


def test_accounts_sees_unpaid_invoices_past_due(db, floor):
    d = Dispatch(
        code="DN-T1",
        vehicle_no="KA-01-A-1234",
        order_id=floor.shirt_order.id,
        buyer_id=floor.shirt_order.buyer_id,
        status=DispatchStatus.confirmed,
        confirmed_at=NOW,
    )
    db.add(d)
    db.flush()
    db.add(
        Invoice(
            code="INV-T1",
            dispatch_id=d.id,
            buyer_id=d.buyer_id,
            order_id=d.order_id,
            subtotal_paise=100,
            tax_paise=5,
            total_paise=105,
            due_date=date(2026, 10, 1),
        )
    )
    db.commit()
    items = of_kind(service.attention_items(db, Role.accounts, NOW), "overdue_invoice")
    assert titles(items) == ["INV-T1 overdue"]
    assert items[0]["detail"] == "due 01 Oct, 9 days late"
    invoice_id = db.scalar(select(Invoice.id).where(Invoice.code == "INV-T1"))
    assert items[0]["href"] == f"/finance/invoices?open={invoice_id}"


def test_accounts_sees_orders_that_will_miss_the_deadline(db, floor):
    floor.shirt_order.deadline = date(2026, 10, 9)
    db.commit()
    items = of_kind(service.attention_items(db, Role.accounts, NOW), "delivery_risk")
    assert titles(items) == ["SO-T1 will be late"]
    assert items[0]["href"] == f"/orders/{floor.shirt_order.id}"


# yarn with no free stock in the store, below its reorder level
def test_store_sees_yarn_below_reorder_level(db, floor):
    db.get(YarnItem, floor.batches[0].yarn_item_id).reorder_level_kg = Decimal(100)
    db.commit()
    items = of_kind(service.attention_items(db, Role.store, NOW), "low_stock")
    assert titles(items) == ["Cotton Ne 40/1 Raw White below reorder level"]
    assert items[0]["severity"] == Severity.critical
    assert items[0]["href"] == "/store/stock"


# R3: low-stock warning also lands on the owner dashboard
def test_owner_sees_yarn_below_reorder_level(db, floor):
    db.get(YarnItem, floor.batches[0].yarn_item_id).reorder_level_kg = Decimal(100)
    db.commit()
    items = service.attention_items(db, Role.owner, NOW)
    assert "Cotton Ne 40/1 Raw White below reorder level" in titles(items)


def warning(item_id, level, projected="-40.000", label="Cotton Ne 30/1 Navy") -> dict:
    return {
        "yarn_item_id": item_id,
        "label": label,
        "projected_free_kg": Decimal(projected),
        "reorder_level_kg": Decimal("100.000"),
        "level": level,
    }


# one low-stock rule: inventory's projected warning, not a second count of free kg here
def test_low_stock_follows_inventory_stock_warnings(db, monkeypatch):
    rows = [warning(1, "short"), warning(2, "low", "60.000", "Cotton Ne 40/1 Black")]
    monkeypatch.setattr(inventory, "stock_warnings", lambda db: rows)
    items = service.attention_items(db, Role.store, NOW)
    assert titles(items) == [
        "Cotton Ne 30/1 Navy below reorder level",
        "Cotton Ne 40/1 Black below reorder level",
    ]
    assert [i["severity"] for i in items] == [Severity.critical, Severity.warn]
    assert items[1]["detail"] == "60.000 kg free after open orders, reorder at 100.000 kg"
    assert (items[0]["entity_type"], items[0]["entity_id"]) == ("yarn_items", 1)


def insight(db, n: int) -> None:
    for k in range(n):
        db.add(
            Insight(
                kind="machine_slowdown",
                severity=Severity.warn,
                entity_type="machines",
                entity_id=100 + k,
                title=f"Loom {k} slowed down",
                facts={},
                narrative="text",
            )
        )
    db.commit()


def late(order_id: int) -> dict:
    return {
        "order_id": order_id,
        "order_code": f"SO-L{order_id}",
        "status": "late",
        "deadline": date(2026, 10, 9),
        "expected_at": NOW + timedelta(days=2),
        "slack_hours": -48.0,
    }


# ten late orders must not push low stock, overdue bills and findings off the owner's list
def test_owner_list_caps_each_kind_and_keeps_the_others(db, monkeypatch):
    monkeypatch.setattr(service, "delivery_board", lambda db, now: [late(k) for k in range(10)])
    monkeypatch.setattr(
        inventory, "stock_warnings", lambda db: [warning(k, "short") for k in range(5)]
    )
    insight(db, 4)
    items = service.attention_items(db, Role.owner, NOW)
    kinds = [i["kind"] for i in items]
    assert kinds.count("delivery_risk") == 3 and kinds.count("low_stock") == 3
    assert kinds.count("insight") == 3
    more = {i["entity_type"]: i for i in items if i["kind"] == "more"}
    assert more["delivery_risk"]["title"] == "7 more orders at risk"
    assert more["delivery_risk"]["href"] == "/orders"
    assert more["delivery_risk"]["severity"] == Severity.critical
    assert more["low_stock"]["title"] == "2 more yarns below reorder level"
    assert more["insight"]["title"] == "1 more open insights"
    assert len(items) <= service.ATTENTION_LIMIT
    # briefing still counts everything, not the capped list
    assert service.briefing(db, Role.owner, NOW)["items"] == 19


# a role that cannot open /insights gets no "more" row pointing there
def test_more_findings_row_only_for_roles_with_the_insights_page(db):
    for k in range(4):
        db.add(
            Insight(
                kind="supplier_defects",
                severity=Severity.warn,
                entity_type="suppliers",
                entity_id=k + 1,
                title=f"Supplier {k}",
                facts={},
                narrative="text",
            )
        )
    db.commit()
    items = service.attention_items(db, Role.qc, NOW)
    assert [i["kind"] for i in items] == ["insight"] * 3


def test_open_insights_join_the_role_list(client_as, db):
    db.add(
        Insight(
            kind="supplier_defects",
            severity=Severity.warn,
            entity_type="suppliers",
            entity_id=1,
            title="SLY lots: colour mismatch 2.6x",
            facts={},
            narrative="text",
        )
    )
    db.commit()
    items = client_as(Role.qc).get("/api/analytics/attention").json()
    assert titles(items) == ["SLY lots: colour mismatch 2.6x"]
    assert items[0]["href"].startswith("/insights?id=")


def test_briefing_starts_with_the_most_urgent_item(client_as, db, floor):
    event(db, floor.loom2, MachineStatus.idle, timedelta(minutes=45))
    event(db, floor.loom1, MachineStatus.breakdown, timedelta(hours=1), "Warp beam snapped")
    text = service.briefing(db, Role.supervisor, NOW)["text"]
    assert text == (
        "2 things need you today, 1 of them urgent. Start with LM-T1 in breakdown "
        "(60 min: Warp beam snapped). Then LM-T2 idle."
    )
    assert client_as(Role.qc).get("/api/analytics/briefing").json()["text"].startswith("Nothing")


# --- role inboxes: each hand-off lands with the person who has to act on it


def done_order(db, floor):
    floor.shirt_weave.status = WorkOrderStatus.done
    db.commit()


def truck(db, floor, code="DN-T9"):
    d = Dispatch(
        code=code,
        order_id=floor.shirt_order.id,
        buyer_id=floor.shirt_order.buyer_id,
        status=DispatchStatus.draft,
    )
    db.add(d)
    db.commit()
    return d


def test_store_inbox_has_yarn_to_issue_and_lots_to_inspect(db, floor):
    floor.batches[1].status = BatchStatus.inspection
    db.commit()
    got = titles(service.attention_items(db, Role.store, NOW))
    assert f"Issue yarn to {floor.shirt_weave.code}" in got
    assert "Inspect YB-T2" in got


def test_only_the_owner_is_told_about_quarantined_lots(db, floor):
    floor.batches[1].status = BatchStatus.quarantined
    db.commit()
    assert "YB-T2 in quarantine" in titles(service.attention_items(db, Role.owner, NOW))
    assert "YB-T2 in quarantine" not in titles(service.attention_items(db, Role.store, NOW))


# yarn on the floor but no loom running or idle: the planner cannot place it, a person must
def test_supervisor_is_told_about_a_job_with_no_machine(db, floor):
    floor.issue(floor.shirt_weave, floor.batches[0], 50)
    got = titles(service.attention_items(db, Role.supervisor, NOW))
    assert f"{floor.shirt_weave.code} has no machine" in got


def test_dispatch_inbox_has_trucks_to_start_load_and_send(db, floor):
    r = roll(db, floor, "R-T5", RollStatus.passed, passed_ago=timedelta(hours=2))
    assert "No truck for SO-T1" not in titles(service.attention_items(db, Role.dispatch, NOW))
    done_order(db, floor)  # made and checked: now it needs a truck
    assert "No truck for SO-T1" in titles(service.attention_items(db, Role.dispatch, NOW))
    d = truck(db, floor)
    assert "DN-T9: 1 roll to load" in titles(service.attention_items(db, Role.dispatch, NOW))
    floor.shirt_order.qty_m = Decimal(60)
    db.add(DispatchRoll(dispatch_id=d.id, roll_id=r.id))
    db.commit()
    assert "DN-T9 is loaded" in titles(service.attention_items(db, Role.dispatch, NOW))


# the rest of the order is another shade band: the truck waits on a supervisor's override
def test_supervisor_is_told_a_truck_needs_a_shade_call(db, floor):
    a = roll(db, floor, "R-T6", RollStatus.passed, passed_ago=timedelta(hours=2))
    b = roll(db, floor, "R-T7", RollStatus.passed, passed_ago=timedelta(hours=1))
    b.shade_band = "B"
    d = truck(db, floor)
    db.add(DispatchRoll(dispatch_id=d.id, roll_id=a.id))
    db.commit()
    assert "DN-T9 needs a shade call" in titles(service.attention_items(db, Role.supervisor, NOW))
    assert "DN-T9 needs a shade call" in titles(service.attention_items(db, Role.owner, NOW))


def test_accounts_is_told_when_last_month_has_no_wage_run(db, floor):
    assert "No wage run for September" in titles(service.attention_items(db, Role.accounts, NOW))
    sept = date(2026, 9, 30)
    db.add(WageRun(period_start=date(2026, 9, 1), period_end=sept, status=WageRunStatus.final))
    db.commit()
    got = titles(service.attention_items(db, Role.accounts, NOW))
    assert "No wage run for September" not in got
