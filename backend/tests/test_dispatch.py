import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.modules.auth.models import Role, User
from app.modules.dispatch import service
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.finance.models import Invoice, InvoiceLine
from app.modules.inventory.models import MoveReason, StockMove
from app.modules.orders.models import OrderStatus
from app.modules.quality.models import Roll, RollStatus
from tests.mill import Mill


def r(id_, length, band="A"):
    return SimpleNamespace(id=id_, length_m=Decimal(length), shade_band=band)


# --- picking (pure)


def test_pick_takes_biggest_that_fit_then_smallest_closer():
    rolls = [r(1, 100), r(2, 80), r(3, 60), r(4, 45), r(5, 30)]
    pick = service.pick_rolls(rolls, Decimal(200))
    # 100 + 80 = 180 fit; 60, 45 overshoot alone... smallest closer of the rest is 30 -> 210
    assert [x.id for x in pick.rolls] == [1, 2, 5]
    assert pick.total == Decimal(210) and pick.overshoot == Decimal(10) and pick.short == 0


def test_pick_prefers_one_band_with_least_overshoot():
    rolls = [r(1, 100, "A"), r(2, 100, "A"), r(3, 120, "B"), r(4, 90, "B")]
    pick = service.pick_rolls(rolls, Decimal(200))
    assert pick.band == "A" and pick.overshoot == 0


def test_pick_reports_short_when_no_band_covers():
    rolls = [r(1, 50, "A"), r(2, 70, "B"), r(3, 40, "B")]
    pick = service.pick_rolls(rolls, Decimal(300))
    assert pick.band == "B" and pick.total == Decimal(110) and pick.short == Decimal(190)


def test_pick_nothing_needed():
    assert service.pick_rolls([r(1, 50)], Decimal(0)) is None


# --- scan, unload, confirm through the API


@pytest.fixture
def mill(db):
    return Mill(db)


@pytest.fixture
def dispatch_for(db, mill):
    def make(order, vehicle="KA-01-AB-1234"):
        d = Dispatch(
            code=f"DN-T{order.id}{mill.n}",
            order_id=order.id,
            buyer_id=order.buyer_id,
            vehicle_no=vehicle,
            status=DispatchStatus.draft,
        )
        mill.n += 1
        db.add(d)
        db.commit()
        return d

    return make


def scan(client, d, roll, key=None):
    body = {"roll_code": roll.code}
    if key:
        body["idempotency_key"] = key
    return client.post(f"/api/dispatch/dispatches/{d.id}/scan", json=body)


def test_scan_loads_roll_and_counts(client_as, db, mill, dispatch_for):
    o = mill.order(300)
    wo = mill.work_order(o)
    r1, r2 = mill.roll(wo, 100), mill.roll(wo, 90)
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)

    res = scan(clerk, d, r1, key="scan-key-0001")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "loading"
    again = scan(clerk, d, r1, key="scan-key-0001")  # scanner retry: same answer, no new row
    assert again.json() == res.json()
    body = scan(clerk, d, r2).json()
    assert body["roll_count"] == 2 and Decimal(body["loaded_m"]) == 190
    assert Decimal(body["remaining_m"]) == 110
    assert len(db.scalars(select(DispatchRoll).where(DispatchRoll.dispatch_id == d.id)).all()) == 2


def test_unpassed_roll_rejected_at_scan(client_as, mill, dispatch_for):
    o = mill.order()
    wo = mill.work_order(o)
    waiting = mill.roll(wo, 80, status=RollStatus.awaiting_qc)
    rework = mill.roll(wo, 80, status=RollStatus.rework)
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)
    for roll in (waiting, rework):
        res = scan(clerk, d, roll)
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "not_passed"
        assert res.json()["error"]["field"] == "roll_code"


def test_roll_of_other_order_rejected(client_as, mill, dispatch_for):
    o1, o2 = mill.order(), mill.order()
    other = mill.roll(mill.work_order(o2), 80)
    res = scan(client_as(Role.dispatch), dispatch_for(o1), other)
    assert res.status_code == 409 and res.json()["error"]["code"] == "wrong_order"


def test_mixed_shade_needs_supervisor_override(client, client_as, mill, dispatch_for):
    o = mill.order()
    wo = mill.work_order(o)
    a, b = mill.roll(wo, 100, band="A"), mill.roll(wo, 100, band="B")
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)
    clerk_auth = client.headers["Authorization"]
    assert scan(clerk, d, a).status_code == 200
    res = scan(clerk, d, b)
    assert res.status_code == 409 and res.json()["error"]["code"] == "shade_mismatch"

    url = f"/api/dispatch/dispatches/{d.id}/shade-override"
    assert clerk.post(url, json={"reason": "buyer agreed"}).status_code == 403
    sup = client_as(Role.supervisor)
    assert sup.post(url, json={"reason": "   "}).status_code == 422
    assert sup.post(url, json={"reason": "Buyer agreed on phone"}).status_code == 200
    client.headers["Authorization"] = clerk_auth
    assert scan(client, d, b).status_code == 200


def test_confirm_makes_invoice_from_exactly_the_loaded_rolls(client_as, db, mill, dispatch_for):
    o = mill.order(200, rate=18500)
    wo = mill.work_order(o)
    r1, r2 = mill.roll(wo, "101.5"), mill.roll(wo, "98.25")
    mill.roll(wo, 60)  # on the shelf, not loaded: must not be invoiced
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)
    scan(clerk, d, r1)
    scan(clerk, d, r2)

    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "confirmed" and res.json()["invoice_code"].startswith("INV-")

    inv = db.scalar(select(Invoice).where(Invoice.dispatch_id == d.id))
    lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).all()
    assert sorted((ln.roll_id, ln.metres) for ln in lines) == sorted(
        [(r1.id, r1.length_m), (r2.id, r2.length_m)]
    )
    # 199.75 m x Rs 185 = Rs 36,953.75; GST 5% = Rs 1,847.69 (half up)
    assert inv.subtotal_paise == 3_695_375
    assert inv.tax_paise == 184_769
    assert inv.total_paise == inv.subtotal_paise + inv.tax_paise
    for roll in (r1, r2):
        db.refresh(roll)
        assert roll.status == RollStatus.dispatched and roll.location_id == mill.loc["DISP"].id
    moves = db.scalars(select(StockMove).where(StockMove.reason == MoveReason.dispatch)).all()
    assert {m.roll_id for m in moves} == {r1.id, r2.id}

    again = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert again.status_code == 409 and again.json()["error"]["code"] == "illegal_transition"


def test_dispatched_roll_cannot_go_on_another_truck(client_as, mill, dispatch_for):
    o = mill.order()
    roll = mill.roll(mill.work_order(o), 100)
    d1, d2 = dispatch_for(o), dispatch_for(o)
    clerk = client_as(Role.dispatch)
    scan(clerk, d1, roll)
    assert scan(clerk, d2, roll).json()["error"]["code"] == "already_dispatched"
    clerk.post(f"/api/dispatch/dispatches/{d1.id}/confirm")
    assert scan(clerk, d2, roll).json()["error"]["code"] == "already_dispatched"


def test_confirm_needs_vehicle_and_rolls(client_as, mill, dispatch_for):
    o = mill.order()
    roll = mill.roll(mill.work_order(o), 100)
    d = dispatch_for(o, vehicle=None)
    clerk = client_as(Role.dispatch)
    empty = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert empty.json()["error"]["code"] == "illegal_transition"  # still draft
    scan(clerk, d, roll)
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert res.status_code == 422 and res.json()["error"]["field"] == "vehicle_no"


def test_unload_last_roll_goes_back_to_draft(client_as, mill, dispatch_for):
    o = mill.order()
    roll = mill.roll(mill.work_order(o), 100)
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)
    scan(clerk, d, roll)
    res = clerk.delete(f"/api/dispatch/dispatches/{d.id}/rolls/{roll.id}")
    assert res.status_code == 200 and res.json()["status"] == "draft"


def test_create_dispatch_only_for_confirmed_order(client_as, mill):
    draft = mill.order(status=OrderStatus.draft)
    mill.db.commit()
    clerk = client_as(Role.dispatch)
    res = clerk.post("/api/dispatch/dispatches", json={"order_id": draft.id})
    assert res.status_code == 409 and res.json()["error"]["field"] == "order_id"
    bad = clerk.post("/api/dispatch/dispatches", json={"order_id": draft.id, "vehicle_no": "!!"})
    assert bad.status_code == 422 and bad.json()["error"]["field"] == "vehicle_no"


def test_detail_proposes_rolls_for_remaining_metres(client_as, mill, dispatch_for):
    o = mill.order(250)
    wo = mill.work_order(o)
    for length, band in [(100, "A"), (90, "A"), (70, "A"), (120, "B"), (60, "B")]:
        mill.roll(wo, length, band=band)
    d = dispatch_for(o)
    body = client_as(Role.dispatch).get(f"/api/dispatch/dispatches/{d.id}").json()
    p = body["proposal"]
    # A: 100 + 90 = 190, closer 70 -> 260 (overshoot 10); B: 120 + 60 = 180, short
    assert p["band"] == "A" and Decimal(p["total_m"]) == 260 and Decimal(p["short_m"]) == 0


def test_corner_check_flags_old_closed_and_leftover(client_as, mill):
    open_o = mill.order(100)
    wo = mill.work_order(open_o)
    mill.roll(wo, 50, days_ago=1)  # fresh, open order: fine
    old = mill.roll(wo, 50, days_ago=12)
    closed = mill.order(100, status=OrderStatus.closed)
    stray = mill.roll(mill.work_order(closed), 40, days_ago=2)
    mill.db.commit()
    items = client_as(Role.dispatch).get("/api/dispatch/corner-check?days=7").json()
    by_code = {i["roll_code"]: i["reasons"] for i in items}
    assert set(by_code) == {old.code, stray.code}
    assert by_code[stray.code] == ["order is closed"]


def test_dispatch_roles(client_as):
    assert client_as(Role.store).get("/api/dispatch/dispatches").status_code == 403


def test_accounts_reads_register_but_cannot_load(client_as, mill, dispatch_for):
    o = mill.order()
    roll = mill.roll(mill.work_order(o), 100)
    d = dispatch_for(o)
    acc = client_as(Role.accounts)
    assert acc.get("/api/dispatch/dispatches").status_code == 200
    assert scan(acc, d, roll).status_code == 403


# --- concurrency: real commits on two connections (committed fixture in conftest)


def test_two_scanners_cannot_load_one_roll_twice(committed, password_hash):
    with Session(committed) as s:
        mill = Mill(s)
        o = mill.order(500)
        roll = mill.roll(mill.work_order(o), 100)
        user = User(name="C", email="c@test.local", role=Role.dispatch, password_hash=password_hash)
        s.add(user)
        ds = [
            Dispatch(code=f"DN-C{i}", order_id=o.id, buyer_id=o.buyer_id, vehicle_no="KA01AB1")
            for i in (1, 2)
        ]
        s.add_all(ds)
        s.commit()
        ids, code, user_id = [d.id for d in ds], roll.code, user.id

    barrier = threading.Barrier(2)
    outcomes = []

    def load(dispatch_id):
        with Session(committed) as s:
            barrier.wait()
            try:
                service.scan(s, s.get(User, user_id), dispatch_id, code, None)
                outcomes.append("ok")
            except Conflict as e:
                outcomes.append(e.code)

    threads = [threading.Thread(target=load, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["already_dispatched", "ok"]
    with Session(committed) as s:
        rid = s.scalar(select(Roll.id).where(Roll.code == code))
        assert len(s.scalars(select(DispatchRoll).where(DispatchRoll.roll_id == rid)).all()) == 1


# the truck that completes the order closes it, so a shipped order stops showing as open or late
def test_confirm_that_ships_the_whole_order_closes_it(client_as, db, mill, dispatch_for):
    o = mill.order(150)
    wo = mill.work_order(o)
    first, second = mill.roll(wo, 100), mill.roll(wo, 60)
    clerk = client_as(Role.dispatch)
    d1 = dispatch_for(o)
    scan(clerk, d1, first)
    assert clerk.post(f"/api/dispatch/dispatches/{d1.id}/confirm").status_code == 200
    db.refresh(o)
    assert o.status == OrderStatus.confirmed
    d2 = dispatch_for(o)
    scan(clerk, d2, second)
    assert clerk.post(f"/api/dispatch/dispatches/{d2.id}/confirm").status_code == 200
    db.refresh(o)
    assert o.status == OrderStatus.closed


# a truck drafted before the order was cancelled can neither load nor leave with an invoice
def test_cancelled_order_cannot_load_or_ship(client_as, db, mill, dispatch_for):
    o = mill.order(200)
    wo = mill.work_order(o)
    loaded, spare = mill.roll(wo, 100), mill.roll(wo, 100)
    d = dispatch_for(o)
    clerk = client_as(Role.dispatch)
    scan(clerk, d, loaded)
    o.status = OrderStatus.cancelled
    db.commit()
    res = scan(clerk, d, spare)
    assert res.status_code == 409 and res.json()["error"]["code"] == "order_not_open"
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert res.status_code == 409 and res.json()["error"]["code"] == "order_not_open"
    assert db.scalar(select(Invoice).where(Invoice.dispatch_id == d.id)) is None
