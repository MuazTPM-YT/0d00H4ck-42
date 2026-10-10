from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.enums import Source
from app.modules.analytics import service
from app.modules.analytics.models import Insight, Severity
from app.modules.auth.models import Role
from app.modules.dispatch.models import Dispatch, DispatchStatus
from app.modules.finance.models import Invoice
from app.modules.masters.models import LocationKind, YarnItem
from app.modules.production.models import MachineEvent, MachineStatus
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


def test_supervisor_sees_stopped_and_long_idle_machines(db, floor):
    event(db, floor.loom1, MachineStatus.breakdown, timedelta(hours=1), "Warp beam snapped")
    event(db, floor.loom2, MachineStatus.idle, timedelta(minutes=45))
    event(db, floor.jigger, MachineStatus.idle, timedelta(minutes=10))
    items = service.attention_items(db, Role.supervisor, NOW)
    assert titles(items) == ["LM-T1 in breakdown", "LM-T2 idle"]
    assert items[0]["severity"] == Severity.critical
    assert items[0]["detail"] == "60 min: Warp beam snapped"
    assert items[0]["href"] == "/floor"


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
    items = service.attention_items(db, Role.accounts, NOW)
    assert titles(items) == ["INV-T1 overdue"]
    assert items[0]["detail"] == "due 01 Oct, 9 days late"


def test_sales_sees_orders_that_will_miss_the_deadline(db, floor):
    floor.shirt_order.deadline = date(2026, 10, 9)
    db.commit()
    items = service.attention_items(db, Role.sales, NOW)
    assert titles(items) == ["SO-T1 will be late"]
    assert items[0]["href"] == f"/orders/{floor.shirt_order.id}"


# yarn with no free stock in the store, below its reorder level
def test_store_sees_yarn_below_reorder_level(db, floor):
    db.get(YarnItem, floor.batches[0].yarn_item_id).reorder_level_kg = Decimal(100)
    db.commit()
    items = service.attention_items(db, Role.store, NOW)
    assert titles(items) == ["Cotton Ne 40/1 Raw White below reorder level"]
    assert items[0]["severity"] == Severity.critical
    assert items[0]["href"] == "/store/stock"


# R3: low-stock warning also lands on the owner dashboard
def test_owner_sees_yarn_below_reorder_level(db, floor):
    db.get(YarnItem, floor.batches[0].yarn_item_id).reorder_level_kg = Decimal(100)
    db.commit()
    items = service.attention_items(db, Role.owner, NOW)
    assert "Cotton Ne 40/1 Raw White below reorder level" in titles(items)


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
