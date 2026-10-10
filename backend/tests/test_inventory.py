from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.enums import Stage
from app.core.errors import AppError
from app.core.security import create_token
from app.modules.auth.models import Role
from app.modules.inventory import service as inv
from app.modules.inventory.labels import parse_label
from app.modules.inventory.models import (
    BatchStatus,
    MoveReason,
    Reservation,
    ReservationStatus,
    YarnBatch,
)
from app.modules.masters.models import LocationKind
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.service import create_work_orders
from tests.inventory_helpers import (
    ensure_locations,
    make_batch,
    make_item,
    make_machine,
    make_order,
    make_supplier,
    plain_fabric,
    spun_fabric,
)

D = Decimal


@pytest.fixture
def api(client, make_user):
    users = {}

    def call(role, method, url, **kw):
        if role not in users:
            users[role] = make_user(role)
        token = create_token(users[role].id, users[role].role)
        return client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)

    return call


@pytest.fixture
def setup(db):
    ensure_locations(db)
    sup = make_supplier(db)
    white40 = make_item(db, "Ne 40/1", "Raw White", reorder=100)
    navy40 = make_item(db, "Ne 40/1", "Navy")
    db.commit()
    return {"sup": sup, "white40": white40, "navy40": navy40}


# ---------------------------------------------------------------- lot selection (pure)


def test_best_fit_picks_smallest_single_lot_that_covers():
    lots = [(1, D(500)), (2, D(120)), (3, D(90)), (4, D(130))]
    assert inv.pick_lots(D(100), lots) == [(2, D("100.000"))]


def test_no_single_lot_means_fewest_lots_largest_first():
    lots = [(1, D(40)), (2, D(70)), (3, D(30)), (4, D(60))]
    # 70 + 60 covers 120 with two lots; smallest-first would need three or four
    assert inv.pick_lots(D(120), lots) == [(2, D("70.000")), (4, D("50.000"))]


def test_equal_lots_tie_breaks_to_older_batch_fifo():
    assert inv.pick_lots(D(50), [(9, D(80)), (3, D(80))]) == [(3, D("50.000"))]


def test_not_enough_takes_everything_free():
    assert inv.pick_lots(D(500), [(1, D(100)), (2, D(0)), (3, D(50))]) == [
        (1, D("100.000")),
        (3, D("50.000")),
    ]


# ---------------------------------------------------------------- labels


def test_parse_label_payload():
    label = parse_label("sup=ksm; LOT=KSM-1; FIB=Cotton; CNT=Ne 30/1; COL=Navy; KG=500")
    assert label == {
        "supplier_code": "KSM",
        "supplier_lot": "KSM-1",
        "fibre": "Cotton",
        "count": "Ne 30/1",
        "colour": "Navy",
        "label_kg": D("500.000"),
    }


@pytest.mark.parametrize(
    "payload",
    [
        "SUP=KSM;LOT=1;FIB=Cotton;CNT=Ne 30/1;COL=Navy",
        "SUP=KSM;LOT=1;FIB=C;CNT=x;COL=y;KG=-5",
        "  ",
    ],
)
def test_unreadable_label_is_422_on_payload(payload):
    with pytest.raises(AppError) as e:
        parse_label(payload)
    assert e.value.status == 422 and e.value.field == "payload"


# ---------------------------------------------------------------- stock rules


def test_quarantined_and_inspection_stock_never_count_as_free(db, setup):
    make_batch(db, setup["sup"], setup["white40"], 300)
    make_batch(db, setup["sup"], setup["white40"], 200, status=BatchStatus.quarantined)
    make_batch(db, setup["sup"], setup["white40"], 150, status=BatchStatus.inspection)
    assert inv.stock_on_hand(db, setup["white40"].id) == D(300)
    assert inv.free_stock(db, setup["white40"].id) == D(300)
    row = next(
        r for r in inv.stock_overview(db)["items"] if r["yarn_item_id"] == setup["white40"].id
    )
    assert (row["free_kg"], row["quarantined_kg"], row["inspection_kg"]) == (300, 200, 150)


def test_stock_never_goes_negative(db, setup):
    batch = make_batch(db, setup["sup"], setup["white40"], 100)
    with pytest.raises(AppError) as e:
        inv.move_yarn(
            db, batch, D("100.001"), LocationKind.store, LocationKind.wip, MoveReason.issue, None
        )
    assert e.value.code == "insufficient_stock"
    assert inv.batch_kg_at(db, batch.id, LocationKind.store) == D(100)


def test_reservation_never_exceeds_free_stock(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 250)
    a = make_order(db, buyer, fabric, "Raw White", 1000)  # needs 210 kg
    b = make_order(db, buyer, fabric, "Raw White", 1000)  # needs 210 kg, only 40 left
    inv.reserve(db, a.id, None)
    inv.reserve(db, b.id, None)
    db.flush()
    held = db.scalars(select(Reservation).where(Reservation.status == "active")).all()
    assert sum(r.kg for r in held) == D(250)
    assert inv.free_stock(db, setup["white40"].id) == D(0)
    alloc = inv.order_allocation(db, b.id)
    assert alloc["lines"][0]["kg_short"] == D(170)


def test_reserve_twice_does_not_double_book(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 500)
    order = make_order(db, buyer, fabric, "Raw White", 1000)  # 210 kg
    inv.reserve(db, order.id, None)
    assert inv.reserve(db, order.id, None) == []
    assert inv.free_stock(db, setup["white40"].id) == D(290)


def test_mixed_lots_warned_when_no_single_lot_covers(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 120)
    make_batch(db, setup["sup"], setup["white40"], 100)
    order = make_order(db, buyer, fabric, "Raw White", 1000)  # 210 kg
    inv.reserve(db, order.id, None)
    db.flush()
    alloc = inv.order_allocation(db, order.id)
    assert alloc["mixed_lots"] is True and len(alloc["lines"][0]["lots"]) == 2
    assert db.scalar(select(AuditLog).where(AuditLog.action == "mixed_lots")) is not None


def test_prefers_single_lot_over_mixing(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 150)
    big = make_batch(db, setup["sup"], setup["white40"], 400)
    order = make_order(db, buyer, fabric, "Raw White", 1000)
    created = inv.reserve(db, order.id, None)
    assert [(r.yarn_batch_id, r.kg) for r in created] == [(big.id, D("210.000"))]


def test_draft_order_cannot_reserve(db, setup, buyer):
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 100, status=OrderStatus.draft)
    with pytest.raises(AppError) as e:
        inv.reserve(db, order.id, None)
    assert e.value.status == 409


def test_projected_free_warns_below_reorder_level(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 250)
    make_order(db, buyer, fabric, "Raw White", 1000)  # confirmed, 210 kg not yet reserved
    row = next(
        r for r in inv.stock_overview(db)["items"] if r["yarn_item_id"] == setup["white40"].id
    )
    assert row["free_kg"] == D(250) and row["needed_by_orders_kg"] == D(210)
    assert row["projected_free_kg"] == D(40) and row["level"] == "low"  # reorder level 100


# ---------------------------------------------------------------- issue and return


@pytest.fixture
def issuing(db, setup, buyer):
    fabric = plain_fabric(db)
    batch = make_batch(db, setup["sup"], setup["white40"], 300)
    mine = make_order(db, buyer, fabric, "Raw White", 500)  # 105 kg
    other = make_order(db, buyer, fabric, "Raw White", 750)  # 157.5 kg
    inv.reserve(db, mine.id, None)
    inv.reserve(db, other.id, None)
    wo = create_work_orders(db, mine.id, None)[0]
    db.commit()
    return {"batch": batch, "wo": wo, "order": mine}


def test_issue_consumes_reservation_and_moves_to_wip(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    inv.issue_to_work_order(db, wo.id, b.id, D(60), user.id)
    db.flush()
    assert inv.batch_kg_at(db, b.id, LocationKind.wip) == D(60)
    alloc = inv.order_allocation(db, issuing["order"].id)["lines"][0]
    assert (alloc["kg_issued"], alloc["kg_reserved"], alloc["kg_short"]) == (60, 45, 0)


def test_over_issue_needs_reason_and_never_takes_other_orders_yarn(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, wo.id, b.id, D(120), user.id)
    assert e.value.field == "reason"
    # 300 in store, 157.5 reserved for the other order: at most 142.5 for this one
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, wo.id, b.id, D("142.501"), user.id, reason="extra weft")
    assert e.value.code == "insufficient_stock"
    inv.issue_to_work_order(db, wo.id, b.id, D(120), user.id, reason="extra weft for trial")


def test_issue_is_idempotent_by_key(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    first = inv.issue_to_work_order(db, wo.id, b.id, D(10), user.id, idempotency_key="scan-0001")
    again = inv.issue_to_work_order(db, wo.id, b.id, D(10), user.id, idempotency_key="scan-0001")
    assert first.id == again.id
    assert inv.batch_kg_at(db, b.id, LocationKind.wip) == D(10)


def test_return_to_store_limited_to_what_the_work_order_holds(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    inv.issue_to_work_order(db, wo.id, b.id, D(30), user.id)
    with pytest.raises(AppError):
        inv.return_to_store(db, wo.id, b.id, D(31), user.id)
    inv.return_to_store(db, wo.id, b.id, D(30), user.id)
    assert inv.batch_kg_at(db, b.id, LocationKind.wip) == D(0)


def test_return_cannot_bring_back_yarn_already_consumed(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    inv.issue_to_work_order(db, wo.id, b.id, D(30), user.id)
    inv.move_yarn(
        db,
        b,
        D(20),
        LocationKind.wip,
        LocationKind.consumed,
        MoveReason.consume,
        user.id,
        ref=("work_order", wo.id),
    )
    assert inv.issue_plan(db, wo.code)["on_floor"][0]["kg"] == D(10)
    with pytest.raises(AppError):
        inv.return_to_store(db, wo.id, b.id, D(11), user.id)
    inv.return_to_store(db, wo.id, b.id, D(10), user.id)


def test_quarantined_batch_cannot_be_issued(db, issuing, make_user):
    user = make_user(Role.store)
    inv.quarantine_batch(db, issuing["batch"].id, user, "shade complaint")
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, issuing["wo"].id, issuing["batch"].id, D(1), user.id)
    assert e.value.status == 409
    # quarantine released every reservation on the batch
    left = db.scalars(
        select(Reservation).where(
            Reservation.yarn_batch_id == issuing["batch"].id,
            Reservation.status == ReservationStatus.active,
        )
    ).all()
    assert left == []


# ---------------------------------------------------------------- receive flow over the API


@pytest.fixture
def delivery(api, setup):
    res = api(
        Role.store,
        "POST",
        "/api/inventory/expected-deliveries",
        json={
            "supplier_id": setup["sup"].id,
            "yarn_item_id": setup["navy40"].id,
            "expected_kg": "500",
            "rate_paise_per_kg": 31000,
            "expected_date": str(date.today() + timedelta(days=2)),
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def label(lot, colour="Navy", kg="250"):
    return f"SUP=TSUP;LOT={lot};FIB=Cotton;CNT=Ne 40/1;COL={colour};KG={kg}"


def new_receipt(api, delivery):
    res = api(
        Role.store,
        "POST",
        "/api/inventory/receipts",
        json={"expected_delivery_id": delivery["id"], "vehicle_no": "ka-05-mn-4521"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["vehicle_no"] == "KA-05-MN-4521"
    return res.json()["id"]


def add(api, rid, **body):
    return api(Role.store, "POST", f"/api/inventory/receipts/{rid}/lines", json=body)


def test_check_label_shows_expected_vs_actual(api, delivery):
    res = api(Role.store, "POST", "/api/inventory/labels/check", json={"payload": label("A1")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["delivery"]["id"] == delivery["id"]
    assert all(row["ok"] for row in body["comparison"])


def test_full_receipt_flow(api, db, delivery, setup):
    rid = new_receipt(api, delivery)
    first = add(api, rid, payload=label("L-1"), received_kg="249")
    assert first.status_code == 200, first.text
    assert first.json()["batch"]["status"] == "inspection"
    assert first.json()["batch"]["code"].startswith("YB-")

    # rescan of the same lot returns the same batch
    again = add(api, rid, payload=label("L-1"), received_kg="249")
    assert again.json()["created"] is False
    assert again.json()["batch"]["id"] == first.json()["batch"]["id"]

    wrong = add(api, rid, payload=label("L-2", colour="Black"), received_kg="250")
    assert wrong.json()["batch"]["status"] == "quarantined"
    assert "colour" in wrong.json()["batch"]["mismatch_notes"]

    missing = add(api, rid, label_missing=True, received_kg="12.5")
    assert missing.json()["batch"]["status"] == "pending_identification"

    # nothing counts until the truck is confirmed
    assert inv.batch_kg_at(db, first.json()["batch"]["id"], LocationKind.inspection) == 0

    done = api(Role.store, "POST", f"/api/inventory/receipts/{rid}/confirm")
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "confirmed"
    assert body["bill_amount_paise"] == 31000 * (249 + 250) + 31000 * 125 // 10
    # quarantined wrong-colour lot does not fill the delivery: 249 + 12.5 of 500 kg
    assert body["expected_delivery"]["status"] == "partially_received"
    assert body["expected_delivery"]["received_kg"] == "261.500"
    assert inv.batch_kg_at(db, wrong.json()["batch"]["id"], LocationKind.quarantine) == 250

    # confirmed receipts are closed
    late = add(api, rid, payload=label("L-9"), received_kg="5")
    assert late.status_code == 409

    approved = api(
        Role.store, "POST", f"/api/inventory/batches/{first.json()['batch']['id']}/approve"
    )
    assert approved.status_code == 200, approved.text
    assert inv.stock_on_hand(db, setup["navy40"].id) == D(249)


def test_weight_variance_flagged_but_never_adjusted(api, delivery):
    rid = new_receipt(api, delivery)
    small_gap = add(api, rid, payload=label("W-1", kg="250"), received_kg="247")  # 1.2%
    assert small_gap.json()["batch"]["mismatch_notes"] is None
    big_gap = add(api, rid, payload=label("W-2", kg="250"), received_kg="240")  # 4%
    batch = big_gap.json()["batch"]
    assert batch["status"] == "inspection"
    assert batch["received_kg"] == "240.000"
    assert "label 250.000 kg, weighed 240" in batch["mismatch_notes"]


def test_partial_delivery_stays_open(api, delivery):
    rid = new_receipt(api, delivery)
    add(api, rid, payload=label("P-1"), received_kg="250")
    body = api(Role.store, "POST", f"/api/inventory/receipts/{rid}/confirm").json()
    assert body["expected_delivery"]["status"] == "partially_received"


def test_label_from_other_supplier_rejected(api, delivery):
    rid = new_receipt(api, delivery)
    res = add(api, rid, payload=label("X").replace("TSUP", "ZZZ"), received_kg="10")
    assert res.status_code == 422 and res.json()["error"]["field"] == "payload"


def test_hand_typed_line_needs_every_label_field(api, delivery):
    rid = new_receipt(api, delivery)
    res = add(api, rid, supplier_lot="H-1", fibre="Cotton", count="Ne 40/1", received_kg="10")
    assert res.status_code == 422 and res.json()["error"]["field"] == "colour"


def test_release_needs_owner_and_reason(api, db, setup):
    batch = make_batch(db, setup["sup"], setup["white40"], 80, status=BatchStatus.quarantined)
    db.commit()
    url = f"/api/inventory/batches/{batch.id}/release"
    assert api(Role.store, "POST", url, json={"reason": "lab retest ok"}).status_code == 403
    blank = api(Role.owner, "POST", url, json={"reason": "   "})
    assert blank.status_code == 422 and blank.json()["error"]["field"] == "reason"
    ok = api(Role.owner, "POST", url, json={"reason": "Lab retest reads Ne 40/1"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert inv.stock_on_hand(db, setup["white40"].id) == D(80)
    row = db.scalar(select(AuditLog).where(AuditLog.action == "release"))
    assert row.reason == "Lab retest reads Ne 40/1"


def test_store_cannot_approve_quarantined_batch(api, db, setup):
    batch = make_batch(db, setup["sup"], setup["white40"], 80, status=BatchStatus.quarantined)
    db.commit()
    res = api(Role.store, "POST", f"/api/inventory/batches/{batch.id}/approve")
    assert res.status_code == 409


def test_tagged_yarn_reserved_for_its_order_on_approve(api, db, setup, buyer):
    order = make_order(db, buyer, plain_fabric(db), "Navy", 500)  # 105 kg Navy
    make_batch(db, setup["sup"], setup["navy40"], 400)  # untagged, older
    tagged = make_batch(
        db, setup["sup"], setup["navy40"], 120, status=BatchStatus.inspection, order_id=order.id
    )
    db.commit()
    res = api(Role.store, "POST", f"/api/inventory/batches/{tagged.id}/approve")
    assert res.status_code == 200, res.text
    lots = inv.order_allocation(db, order.id)["lines"][0]["lots"]
    assert [(lot["yarn_batch_id"], lot["reserved_kg"]) for lot in lots] == [(tagged.id, 105)]


def test_inventory_role_checks(api, setup):
    assert api(Role.accounts, "POST", "/api/inventory/batches/1/approve").status_code == 403
    assert (
        api(Role.qc, "POST", "/api/inventory/receipts", json={"supplier_id": 1}).status_code == 403
    )
    assert api(Role.qc, "GET", "/api/inventory/stock").status_code == 200
    issue = {"work_order_id": 1, "yarn_batch_id": 1, "kg": "1"}
    assert api(Role.supervisor, "POST", "/api/inventory/issues", json=issue).status_code == 403


def test_qr_svg_endpoint(api, setup):
    res = api(Role.store, "GET", "/api/inventory/qr.svg", params={"data": label("Q")})
    assert res.status_code == 200 and res.headers["content-type"] == "image/svg+xml"
    assert res.text.startswith("<svg")


# other modules lock batches and orders with FOR UPDATE; display relationships must not add joins
def test_batches_and_orders_can_be_row_locked(db, setup, buyer):
    batch = make_batch(db, setup["sup"], setup["white40"], 10)
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 10)
    locked = db.scalar(select(YarnBatch).where(YarnBatch.id == batch.id).with_for_update())
    assert locked.yarn_item.colour == "Raw White"
    assert db.scalar(select(Order).where(Order.id == order.id).with_for_update()).buyer is not None


# demo: with no yarn request at all, a walk-in label still scans and lands as a lot
def test_walk_in_label_needs_no_request(api, setup):
    labels = api(Role.store, "GET", "/api/inventory/sample-labels").json()
    walk_in = [lbl for lbl in labels if lbl["kind"] == "walk_in"]
    assert len(walk_in) == 2 and all(lbl["delivery_id"] is None for lbl in walk_in)
    payload = walk_in[0]["payload"]
    check = api(Role.store, "POST", "/api/inventory/labels/check", json={"payload": payload})
    assert check.status_code == 200 and check.json()["delivery"] is None
    assert check.json()["suggested_rate_paise_per_kg"] is None  # never bought: nothing to offer
    receipt = api(
        Role.store, "POST", "/api/inventory/receipts", json={"supplier_id": setup["sup"].id}
    )
    rid = receipt.json()["id"]
    assert add(api, rid, payload=payload, received_kg="500").json()["error"]["field"] == "rate"
    line = add(api, rid, payload=payload, received_kg="500", rate_paise_per_kg=28500)
    assert line.status_code == 200, line.text
    assert line.json()["batch"]["status"] == "inspection"
    again = api(Role.store, "POST", "/api/inventory/labels/check", json={"payload": payload})
    assert again.json()["suggested_rate_paise_per_kg"] == 28500  # this supplier's last GRN rate


# ---------------------------------------------------------------- workflow spine


def test_yarn_goes_to_first_stage_only(db, setup, buyer, make_user):
    user = make_user(Role.store)
    batch = make_batch(db, setup["sup"], setup["white40"], 300)
    order = make_order(db, buyer, spun_fabric(db), "Raw White", 500)
    spin, weave = create_work_orders(db, order.id, None)
    inv.reserve(db, order.id, None)
    db.commit()
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, weave.id, batch.id, D(10), user.id)
    assert e.value.status == 409
    assert (
        e.value.message == f"Issue yarn to {spin.code} (spinning), the first stage of {order.code}"
    )
    with pytest.raises(AppError) as e:
        inv.issue_plan(db, weave.code)
    assert e.value.status == 409 and spin.code in e.value.message
    inv.issue_to_work_order(db, spin.id, batch.id, D(10), user.id)
    assert inv.issue_plan(db, spin.code)["on_floor"][0]["kg"] == D(10)


def test_dyeing_work_order_points_at_the_first_stage(db, setup, buyer, dyed_fabric, make_user):
    user = make_user(Role.store)
    batch = make_batch(db, setup["sup"], setup["white40"], 300)
    order = make_order(db, buyer, dyed_fabric, "Maroon", 500)
    weave, dye = create_work_orders(db, order.id, None)
    db.commit()
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, dye.id, batch.id, D(1), user.id, reason="test")
    assert e.value.status == 409
    assert e.value.message.startswith("Dyeing work orders take fabric, not yarn")
    assert weave.code in e.value.message


@pytest.fixture
def published(monkeypatch):
    sent = []
    monkeypatch.setattr(inv.events, "publish", lambda topic, data: sent.append((topic, data)))
    return sent


def test_approve_reserves_for_short_orders(api, db, setup, buyer, published):
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 500)  # 105 kg, nothing reserved
    batch = make_batch(db, setup["sup"], setup["white40"], 150, status=BatchStatus.inspection)
    db.commit()
    res = api(Role.store, "POST", f"/api/inventory/batches/{batch.id}/approve")
    assert res.status_code == 200, res.text
    assert inv.order_allocation(db, order.id)["lines"][0]["kg_reserved"] == D(105)
    assert ("orders", {"type": "reserved", "id": order.id}) in published


def test_quarantine_moves_order_to_another_lot_and_publishes_order_ids(
    db, setup, buyer, make_user, published
):
    user = make_user(Role.store)
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 500)  # 105 kg
    first = make_batch(db, setup["sup"], setup["white40"], 120)
    spare = make_batch(db, setup["sup"], setup["white40"], 200)
    inv.reserve(db, order.id, None)
    db.commit()
    inv.quarantine_batch(db, first.id, user, "shade complaint")
    lots = inv.order_allocation(db, order.id)["lines"][0]["lots"]
    assert [(lot["yarn_batch_id"], lot["reserved_kg"]) for lot in lots if lot["reserved_kg"]] == [
        (spare.id, D(105))
    ]
    order_events = [data for topic, data in published if topic == "orders"]
    assert order_events and all(e["id"] == order.id for e in order_events)


def test_lot_tagged_to_another_live_order_is_not_reserved(db, setup, buyer):
    fabric = plain_fabric(db)
    owner = make_order(db, buyer, fabric, "Raw White", 500, status=OrderStatus.draft)
    other = make_order(db, buyer, fabric, "Raw White", 500)
    tagged = make_batch(db, setup["sup"], setup["white40"], 300, order_id=owner.id)
    assert inv.reserve(db, other.id, None) == []
    owner.status = OrderStatus.cancelled
    db.flush()
    assert [(r.yarn_batch_id, r.kg) for r in inv.reserve(db, other.id, None)] == [
        (tagged.id, D(105))
    ]


def test_return_puts_yarn_back_on_hold_for_its_order(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    inv.issue_to_work_order(db, wo.id, b.id, D(60), user.id)
    inv.return_to_store(db, wo.id, b.id, D(30), user.id)
    line = inv.order_allocation(db, issuing["order"].id)["lines"][0]
    assert (line["kg_issued"], line["kg_reserved"], line["kg_short"]) == (30, 75, 0)
    # the other order keeps its 157.5 kg: free = 300 - 30 on the floor - 75 - 157.5
    assert inv.free_stock(db, b.yarn_item_id) == D("37.5")


def test_issue_from_unreserved_lot_retires_now_surplus_reservation(db, setup, buyer, make_user):
    user = make_user(Role.store)
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 500)  # 105 kg
    held = make_batch(db, setup["sup"], setup["white40"], 105)
    other = make_batch(db, setup["sup"], setup["white40"], 400)
    inv.reserve(db, order.id, None)
    wo = create_work_orders(db, order.id, None)[0]
    db.commit()
    inv.issue_to_work_order(db, wo.id, other.id, D(105), user.id, reason="lot on the trolley")
    line = inv.order_allocation(db, order.id)["lines"][0]
    assert (line["kg_issued"], line["kg_reserved"], line["kg_short"]) == (105, 0, 0)
    assert inv.free_stock(db, setup["white40"].id) == D(400)
    assert inv.reserved_by_batch(db, [held.id]) == {}


def test_issue_from_other_lot_keeps_reservation_still_needed(db, setup, buyer, make_user):
    user = make_user(Role.store)
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 500)  # 105 kg
    held = make_batch(db, setup["sup"], setup["white40"], 60)
    inv.reserve(db, order.id, None)  # 60 of 105
    other = make_batch(db, setup["sup"], setup["white40"], 400)
    wo = create_work_orders(db, order.id, None)[0]
    db.commit()
    inv.issue_to_work_order(db, wo.id, other.id, D(45), user.id, reason="cover the gap")
    line = inv.order_allocation(db, order.id)["lines"][0]
    assert (line["kg_issued"], line["kg_reserved"], line["kg_short"]) == (45, 60, 0)
    assert inv.reserved_by_batch(db, [held.id]) == {held.id: D(60)}


def test_rejected_lot_on_draft_truck_is_not_moved_billed_or_counted(api, db, delivery):
    rid = new_receipt(api, delivery)
    keep = add(api, rid, payload=label("K-1", kg="300"), received_kg="300").json()["batch"]
    bad = add(api, rid, payload=label("K-2", kg="200"), received_kg="200").json()["batch"]
    url = f"/api/inventory/batches/{bad['id']}/reject"
    res = api(Role.store, "POST", url, json={"reason": "wet cones"})
    assert res.status_code == 200, res.text
    body = api(Role.store, "POST", f"/api/inventory/receipts/{rid}/confirm").json()
    assert body["bill_amount_paise"] == 31000 * 300
    assert body["expected_delivery"]["received_kg"] == "300.000"
    assert body["expected_delivery"]["status"] == "partially_received"
    assert inv.balances(db, [bad["id"]]) == {}
    assert inv.batch_kg_at(db, keep["id"], LocationKind.inspection) == D(300)


def test_remove_lot_and_discard_empty_draft_truck(api, db, delivery):
    rid = new_receipt(api, delivery)
    lot = add(api, rid, payload=label("D-1"), received_kg="250").json()["batch"]
    busy = api(Role.store, "DELETE", f"/api/inventory/receipts/{rid}")
    assert busy.status_code == 409
    res = api(Role.store, "DELETE", f"/api/inventory/receipts/{rid}/lines/{lot['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["batches"] == []
    assert db.get(YarnBatch, lot["id"]) is None
    assert api(Role.store, "DELETE", f"/api/inventory/receipts/{rid}").status_code == 204
    assert api(Role.store, "GET", f"/api/inventory/receipts/{rid}").status_code == 404
    assert db.scalar(select(AuditLog).where(AuditLog.action == "discard")) is not None


def test_confirmed_truck_lots_cannot_be_removed(api, delivery):
    rid = new_receipt(api, delivery)
    lot = add(api, rid, payload=label("C-1"), received_kg="250").json()["batch"]
    api(Role.store, "POST", f"/api/inventory/receipts/{rid}/confirm")
    res = api(Role.store, "DELETE", f"/api/inventory/receipts/{rid}/lines/{lot['id']}")
    assert res.status_code == 409


def test_walk_in_lot_can_be_tagged_to_an_order(api, db, setup, buyer):
    order = make_order(db, buyer, plain_fabric(db), "Navy", 500)
    gone = make_order(db, buyer, plain_fabric(db, code="TSHIRT2"), "Navy", 500)
    gone.status = OrderStatus.cancelled
    db.commit()
    receipt = api(
        Role.store, "POST", "/api/inventory/receipts", json={"supplier_id": setup["sup"].id}
    )
    rid = receipt.json()["id"]
    body = {"payload": label("T-1"), "received_kg": "250", "rate_paise_per_kg": 30000}
    res = add(api, rid, **body, order_id=order.id)
    assert res.status_code == 200, res.text
    assert res.json()["batch"]["order_id"] == order.id
    bad = add(api, rid, **{**body, "payload": label("T-2")}, order_id=gone.id)
    assert bad.status_code == 409 and bad.json()["error"]["field"] == "order_id"


def test_needs_yarn_lists_first_stage_jobs_running_first(api, db, setup, buyer, make_user):
    fabric = spun_fabric(db)
    late = make_order(db, buyer, fabric, "Raw White", 500)  # 105 kg
    soon = make_order(db, buyer, fabric, "Raw White", 500)
    soon.deadline = date.today() + timedelta(days=5)
    late_spin, _ = create_work_orders(db, late.id, None)
    soon_spin, _ = create_work_orders(db, soon.id, None)
    late_spin.machine_id = make_machine(db, Stage.spinning).id
    late_spin.status = "running"
    batch = make_batch(db, setup["sup"], setup["white40"], 500)
    inv.reserve(db, soon.id, None)
    db.commit()
    rows = api(Role.supervisor, "GET", "/api/inventory/needs-yarn").json()
    assert [r["wo_code"] for r in rows] == [late_spin.code, soon_spin.code]
    assert rows[0]["machine_code"] and rows[1]["kg_reserved"] == "105.000"
    inv.issue_to_work_order(db, soon_spin.id, batch.id, D(105), make_user(Role.owner).id)
    db.commit()
    rows = api(Role.store, "GET", "/api/inventory/needs-yarn").json()
    assert [r["wo_code"] for r in rows] == [late_spin.code]
    assert api(Role.accounts, "GET", "/api/inventory/needs-yarn").status_code == 403


def test_untagged_yarn_on_order_counts_once(api, db, setup, buyer):
    fabric = plain_fabric(db)
    a = make_order(db, buyer, fabric, "Navy", 500)  # 105 kg Navy each, no stock
    b = make_order(db, buyer, fabric, "Navy", 500)
    b.deadline = date(2027, 6, 1)
    db.commit()
    res = api(
        Role.store,
        "POST",
        "/api/inventory/expected-deliveries",
        json={
            "supplier_id": setup["sup"].id,
            "yarn_item_id": setup["navy40"].id,
            "expected_kg": "150",
            "rate_paise_per_kg": 31000,
            "expected_date": str(date.today() + timedelta(days=2)),
        },
    )
    assert res.status_code == 201, res.text
    rows = {r["order_id"]: r for r in inv.to_buy(db) if r["yarn_item_id"] == setup["navy40"].id}
    assert (rows[a.id]["on_order_kg"], rows[a.id]["to_buy_kg"]) == (D(105), D(0))
    assert (rows[b.id]["on_order_kg"], rows[b.id]["to_buy_kg"]) == (D(45), D(60))
    row = next(r for r in inv.stock_warnings(db) if r["yarn_item_id"] == setup["navy40"].id)
    assert (row["on_order_kg"], row["projected_free_kg"], row["level"]) == (150, -60, "short")


# a Raw White job never gets Navy yarn, even with a reason typed: wrong yarn = wrong lineage
def test_issue_refuses_yarn_the_order_does_not_use(db, setup, issuing, make_user):
    user = make_user(Role.store)
    navy = make_batch(db, setup["sup"], setup["navy40"], 100)
    db.commit()
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, issuing["wo"].id, navy.id, D(10), user.id, reason="short")
    assert e.value.status == 409 and e.value.code == "wrong_yarn"


# a cancelled order's job takes no more yarn from the store
def test_issue_refuses_a_cancelled_orders_job(db, issuing, make_user):
    user = make_user(Role.store)
    issuing["order"].status = OrderStatus.cancelled
    db.commit()
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, issuing["wo"].id, issuing["batch"].id, D(10), user.id)
    assert e.value.status == 409 and e.value.code == "order_not_open"
