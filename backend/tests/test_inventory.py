from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.errors import AppError
from app.core.security import create_token
from app.modules.auth.models import Role
from app.modules.inventory import service as inv
from app.modules.inventory.labels import parse_label
from app.modules.inventory.models import BatchStatus, MoveReason, Reservation, ReservationStatus
from app.modules.masters.models import LocationKind
from app.modules.orders.models import OrderStatus
from app.modules.production.service import create_work_orders
from tests.inventory_helpers import (
    ensure_locations,
    make_batch,
    make_item,
    make_order,
    make_supplier,
    plain_fabric,
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
    a = make_order(db, buyer, fabric, "Raw White", 1000)  # needs 200 kg
    b = make_order(db, buyer, fabric, "Raw White", 1000)  # needs 200 kg, only 50 left
    inv.reserve(db, a.id, None)
    inv.reserve(db, b.id, None)
    db.flush()
    held = db.scalars(select(Reservation).where(Reservation.status == "active")).all()
    assert sum(r.kg for r in held) == D(250)
    assert inv.free_stock(db, setup["white40"].id) == D(0)
    alloc = inv.order_allocation(db, b.id)
    assert alloc["lines"][0]["kg_short"] == D(150)


def test_reserve_twice_does_not_double_book(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 500)
    order = make_order(db, buyer, fabric, "Raw White", 1000)
    inv.reserve(db, order.id, None)
    assert inv.reserve(db, order.id, None) == []
    assert inv.free_stock(db, setup["white40"].id) == D(300)


def test_mixed_lots_warned_when_no_single_lot_covers(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 120)
    make_batch(db, setup["sup"], setup["white40"], 100)
    order = make_order(db, buyer, fabric, "Raw White", 1000)  # 200 kg
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
    assert [(r.yarn_batch_id, r.kg) for r in created] == [(big.id, D("200.000"))]


def test_draft_order_cannot_reserve(db, setup, buyer):
    order = make_order(db, buyer, plain_fabric(db), "Raw White", 100, status=OrderStatus.draft)
    with pytest.raises(AppError) as e:
        inv.reserve(db, order.id, None)
    assert e.value.status == 409


def test_projected_free_warns_below_reorder_level(db, setup, buyer):
    fabric = plain_fabric(db)
    make_batch(db, setup["sup"], setup["white40"], 250)
    make_order(db, buyer, fabric, "Raw White", 1000)  # confirmed, 200 kg not yet reserved
    row = next(
        r for r in inv.stock_overview(db)["items"] if r["yarn_item_id"] == setup["white40"].id
    )
    assert row["free_kg"] == D(250) and row["needed_by_orders_kg"] == D(200)
    assert row["projected_free_kg"] == D(50) and row["level"] == "low"  # reorder level 100


# ---------------------------------------------------------------- issue and return


@pytest.fixture
def issuing(db, setup, buyer):
    fabric = plain_fabric(db)
    batch = make_batch(db, setup["sup"], setup["white40"], 300)
    mine = make_order(db, buyer, fabric, "Raw White", 500)  # 100 kg
    other = make_order(db, buyer, fabric, "Raw White", 750)  # 150 kg
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
    assert (alloc["kg_issued"], alloc["kg_reserved"], alloc["kg_short"]) == (60, 40, 0)


def test_over_issue_needs_reason_and_never_takes_other_orders_yarn(db, issuing, make_user):
    user = make_user(Role.store)
    b, wo = issuing["batch"], issuing["wo"]
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, wo.id, b.id, D(120), user.id)
    assert e.value.field == "reason"
    # 300 in store, 150 reserved for the other order: at most 150 for this one
    with pytest.raises(AppError) as e:
        inv.issue_to_work_order(db, wo.id, b.id, D(151), user.id, reason="extra weft")
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
    assert body["expected_delivery"]["status"] == "received"  # 511.5 of 500 kg
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
    order = make_order(db, buyer, plain_fabric(db), "Navy", 500)  # 100 kg Navy
    make_batch(db, setup["sup"], setup["navy40"], 400)  # untagged, older
    tagged = make_batch(
        db, setup["sup"], setup["navy40"], 120, status=BatchStatus.inspection, order_id=order.id
    )
    db.commit()
    res = api(Role.store, "POST", f"/api/inventory/batches/{tagged.id}/approve")
    assert res.status_code == 200, res.text
    lots = inv.order_allocation(db, order.id)["lines"][0]["lots"]
    assert [(lot["yarn_batch_id"], lot["reserved_kg"]) for lot in lots] == [(tagged.id, 100)]


def test_inventory_role_checks(api, setup):
    assert api(Role.sales, "POST", "/api/inventory/batches/1/approve").status_code == 403
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
