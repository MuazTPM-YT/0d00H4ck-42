import importlib.util
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.auth.models import Role
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrderStatus as W
from app.modules.quality.models import RollStatus
from app.modules.tracking import service
from app.modules.tracking.schemas import BuyerStage as S
from tests.mill import Mill

D = Decimal


def metres(**kw):
    zero = ("produced", "in_production", "in_qc", "passed", "rejected", "shipped")
    return {k: D(0) for k in zero} | {k: D(v) for k, v in kw.items()}


def wo(stage, status, planned=1000, produced=0, unit=None):
    row = {"stage": stage, "status": status, "planned": D(planned), "produced": D(produced)}
    return row | {"unit": unit}


@pytest.mark.parametrize(
    ("status", "stages", "m", "expected"),
    [
        (OrderStatus.draft, [], metres(), (S.order_received, None, None)),
        (OrderStatus.cancelled, [wo("weaving", W.running)], metres(), (S.cancelled, None, None)),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.waiting)],
            metres(),
            (S.waiting_for_yarn, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.running, 1000, 250)],
            metres(produced=250, in_qc=250),
            (S.in_production, "weaving", 25),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done, 1000, 1000), wo("dyeing", W.queued)],
            metres(produced=1000, in_production=1000),
            (S.in_production, "dyeing", 0),
        ),
        # loom still has work but already made its planned metres: QC is where it waits
        (
            OrderStatus.confirmed,
            [wo("weaving", W.running, 1000, 1000)],
            metres(produced=1000, in_qc=600, passed=400),
            (S.being_checked, None, None),
        ),
        # planned 1050 (5% allowance), 525 m woven of a 1000 m order reads 52%, not 50%
        (
            OrderStatus.confirmed,
            [wo("weaving", W.running, 1050, 525, "m")],
            metres(produced=525, in_production=525),
            (S.in_production, "weaving", 52),
        ),
        # rolls at the QC table, loom paused between jobs: being checked, not production
        (
            OrderStatus.confirmed,
            [wo("weaving", W.queued, 1000, 300)],
            metres(produced=300, in_qc=300),
            (S.being_checked, None, None),
        ),
        # all work done, everything decided, short of the order: not "production 100%"
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done, 1000, 1000)],
            metres(produced=1000, passed=900, rejected=100),
            (S.short, None, None),
        ),
        # within 2%: ready
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done, 1000, 1000)],
            metres(produced=1000, passed=985, rejected=15),
            (S.ready_to_ship, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done, 1000, 1000)],
            metres(produced=1000, in_qc=400, passed=600),
            (S.being_checked, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.running, 1000, 1000)],
            metres(produced=1000, passed=1000),
            (S.ready_to_ship, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done)],
            metres(produced=980, passed=900, rejected=80),
            (S.short, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done)],
            metres(produced=1000, passed=700, shipped=300),
            (S.partly_shipped, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done)],
            metres(shipped=1000),
            (S.shipped, None, None),
        ),
        (
            OrderStatus.confirmed,
            [wo("weaving", W.done)],
            metres(shipped=985),
            (S.shipped, None, None),
        ),
        (OrderStatus.closed, [wo("weaving", W.done)], metres(shipped=950), (S.shipped, None, None)),
    ],
)
def test_derive_stage(status, stages, m, expected):
    assert service.derive_stage(status, D(1000), stages, m, yarn_covered=False) == expected


# yarn reserved and nothing started: planned, not waiting for yarn
def test_covered_order_not_started_is_planned():
    stages = [wo("weaving", W.waiting)]
    got = service.derive_stage(OrderStatus.confirmed, D(1000), stages, metres(), True)
    assert got == (S.planned, None, None)


# the real seed script, inside the test transaction (rolled back after)
def test_stage_for_every_seeded_order(db):
    path = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed", path)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    seed.seed_masters(db)
    seed.seed_demo(db)
    db.flush()

    got = {}
    for o in db.scalars(select(Order).order_by(Order.id)):
        card = service.order_stage(db, o.id)
        got[(o.colour, str(o.qty_m))] = (card["stage"], card["production_stage"])
    assert got == {
        ("Raw White", "225.000"): (S.shipped, None),  # closed, 3 rolls dispatched
        ("Navy", "1200.000"): (S.in_production, "weaving"),  # loom running
        ("Maroon", "800.000"): (S.in_production, "dyeing"),  # woven, waiting at dyeing
        ("Raw White", "1000.000"): (S.in_production, "spinning"),  # spinning paused
        ("Black", "600.000"): (S.order_received, None),  # draft
        ("Bottle Green", "400.000"): (S.cancelled, None),
        ("Raw White", "300.000"): (S.ready_to_ship, None),  # 427 m passed for 300 m
    }


def test_public_page_shows_stage_and_never_money(client, db):
    mill = Mill(db)
    o = mill.order(200, rate=18500)
    w = mill.work_order(o)
    mill.roll(w, 120)
    mill.roll(w, 90, status=RollStatus.awaiting_qc)
    db.commit()

    res = client.get(f"/api/track/{o.tracking_token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "being_checked"
    assert body["metres"]["passed"] == "120.000" and body["metres"]["in_qc"] == "90.000"
    text = json.dumps(body).lower()
    for word in ("paise", "rate", "cost", "price", "token", "buyer", "_id"):
        assert word not in text, word


# rejects are staff business: buyer link never carries them, office view does
def test_rejected_metres_only_for_staff(client_as, client, db):
    mill = Mill(db)
    o = mill.order(200)
    w = mill.work_order(o)
    mill.roll(w, 120)
    mill.roll(w, 40, status=RollStatus.rejected)
    db.commit()

    public = client.get(f"/api/track/{o.tracking_token}").json()
    assert "rejected" not in public["metres"]
    assert "reject" not in json.dumps(public).lower()
    assert public["metres"]["produced"] == "120.000"
    staff = client_as(Role.accounts).get(f"/api/track/orders/{o.id}").json()
    assert staff["metres"]["rejected"] == "40.000"


def test_bad_or_rotated_token_is_404(client_as, client, db):
    o = Mill(db).order()
    db.commit()
    old = o.tracking_token
    assert client.get("/api/track/not-a-real-token-123").status_code == 404

    res = client_as(Role.accounts).post(f"/api/track/orders/{o.id}/rotate-token")
    assert res.status_code == 200
    assert res.json()["tracking_token"] != old
    assert client.get(f"/api/track/{old}").status_code == 404
    assert client.get(f"/api/track/{res.json()['tracking_token']}").status_code == 200


def test_order_view_lists_rolls_and_roles(client_as, db):
    mill = Mill(db)
    o = mill.order()
    mill.roll(mill.work_order(o), 100)
    db.commit()
    assert client_as(Role.qc).get(f"/api/track/orders/{o.id}").status_code == 403
    body = client_as(Role.accounts).get(f"/api/track/orders/{o.id}").json()
    assert [r["status"] for r in body["rolls"]] == ["passed"]
    assert body["buyer_name"] == "Mill Buyer"


# staff share the link on whatsapp or email; buyer contact never reaches the public page
def test_order_view_carries_buyer_contact_for_sharing(client_as, client, db):
    mill = Mill(db)
    mill.buyer.contact_name, mill.buyer.phone = "Ravi", "+91 98450 10037"
    mill.buyer.email = "ravi@millbuyer.example"
    o = mill.order()
    db.commit()
    body = client_as(Role.accounts).get(f"/api/track/orders/{o.id}").json()
    assert body["buyer_contact"] == "Ravi"
    assert body["buyer_phone"] == "+91 98450 10037"
    assert body["buyer_email"] == "ravi@millbuyer.example"
    public = json.dumps(client.get(f"/api/track/{o.tracking_token}").json())
    assert "98450" not in public and "ravi" not in public.lower()


def test_late_when_forecast_lands_after_deadline(client, db):
    from datetime import date, timedelta

    mill = Mill(db)
    o = mill.order(deadline=date.today() - timedelta(days=3))
    draft = mill.order(status=OrderStatus.draft, deadline=date.today() - timedelta(days=3))
    db.commit()
    body = client.get(f"/api/track/{o.tracking_token}").json()
    assert body["risk"] == "late" and body["projected_finish"] > str(o.deadline)
    # no forecast outside production, but a missed deadline is still late
    body = client.get(f"/api/track/{draft.tracking_token}").json()
    assert body["risk"] == "late" and body["projected_finish"] is None


# order list column: stage for many orders in one call, office roles only
def test_stages_for_a_page_of_orders(client_as, db):
    mill = Mill(db)
    ready = mill.order(100)
    mill.roll(mill.work_order(ready), 120)
    waiting = mill.order(200)
    db.commit()
    rows = client_as(Role.accounts).get(f"/api/track/stages?ids={ready.id},{waiting.id}").json()
    by_id = {r["order_id"]: r for r in rows}
    assert by_id[ready.id]["stage"] == "ready_to_ship" and by_id[ready.id]["passed_m"] == "120.000"
    assert by_id[waiting.id]["stage"] == "waiting_for_yarn"
    assert client_as(Role.dispatch).get("/api/track/stages?ids=4,x").status_code == 422
    bad = client_as(Role.qc).get(f"/api/track/stages?ids={ready.id}")
    assert bad.status_code == 403


# woven rolls not yet at QC are in production, not in QC
def test_in_process_rolls_count_as_in_production(client_as, db):
    mill = Mill(db)
    o = mill.order(300)
    w = mill.work_order(o, status=W.running)
    mill.roll(w, 100, status=RollStatus.in_process)
    mill.roll(w, 50, status=RollStatus.awaiting_qc)
    db.commit()
    m = client_as(Role.accounts).get(f"/api/track/orders/{o.id}").json()["metres"]
    assert (m["in_production"], m["in_qc"]) == ("100.000", "50.000")


# shipped order: no forecast and no risk flag on the card
def test_shipped_order_shows_no_estimate(client, db, monkeypatch):
    from app.modules.analytics import service as analytics

    mill = Mill(db)
    o = mill.order(100, deadline=date.today() - timedelta(days=3))
    mill.roll(mill.work_order(o), 100, status=RollStatus.dispatched)
    db.commit()

    def boom(*a, **k):
        raise AssertionError("no forecast for a shipped order")

    monkeypatch.setattr(analytics, "delivery_estimate", boom)
    body = client.get(f"/api/track/{o.tracking_token}").json()
    assert body["stage"] == "shipped"
    assert (body["projected_finish"], body["risk"]) == (None, None)


# list column and card come from the same derive: stage agrees for every order
def test_list_and_card_agree(client_as, db):
    mill = Mill(db)
    short = mill.order(1000)
    w = mill.work_order(short)
    mill.roll(w, 900)
    mill.roll(w, 100, status=RollStatus.rejected)
    db.commit()
    office = client_as(Role.accounts)
    row = office.get(f"/api/track/stages?ids={short.id}").json()[0]
    card = office.get(f"/api/track/orders/{short.id}").json()
    public = office.get(f"/api/track/{short.tracking_token}").json()
    assert row["stage"] == card["stage"] == public["stage"] == "short"


# buyer sees every truck that left: challan, when, rolls, metres, vehicle, driver
def test_buyer_link_lists_trucks_that_left(client, db):
    from datetime import UTC, datetime

    from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus

    mill = Mill(db)
    o = mill.order(200)
    w = mill.work_order(o)
    gone = [mill.roll(w, 60, status=RollStatus.dispatched) for _ in range(2)]
    waiting = mill.roll(w, 80)
    left = Dispatch(
        code="DN-T1",
        order_id=o.id,
        buyer_id=o.buyer_id,
        vehicle_no="KA 05 MN 4321",
        driver="Suresh Kumar",
        status=DispatchStatus.confirmed,
        confirmed_at=datetime(2026, 10, 9, 6, 30, tzinfo=UTC),
        delivery_otp="482913",
    )
    draft = Dispatch(code="DN-T2", order_id=o.id, buyer_id=o.buyer_id)
    db.add_all([left, draft])
    db.flush()
    db.add_all([DispatchRoll(dispatch_id=left.id, roll_id=r.id) for r in gone])
    db.add(DispatchRoll(dispatch_id=draft.id, roll_id=waiting.id))
    db.commit()

    body = client.get(f"/api/track/{o.tracking_token}").json()
    assert body["deliveries"] == [
        {
            "challan": "DN-T1",
            "left_at": "2026-10-09T06:30:00Z",
            "rolls": 2,
            "metres": "120.000",
            "vehicle_no": "KA 05 MN 4321",
            "driver": "Suresh Kumar",
            "delivered_at": None,
            "received_by": None,
            "code": "482913",
            "code_locked": False,
        }
    ]
