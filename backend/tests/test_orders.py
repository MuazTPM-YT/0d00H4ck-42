import threading
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.security import create_token
from app.modules.auth.models import Role
from app.modules.inventory import service as inv
from app.modules.inventory.models import (
    ExpectedDelivery,
    Receipt,
    Reservation,
    ReservationStatus,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import Buyer, FabricRecipe, FabricType, FabricTypeStage, YarnItem
from app.modules.orders.models import Order
from app.modules.production.models import WorkOrder
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
def stocked(db, dyed_fabric, buyer):
    ensure_locations(db)
    sup = make_supplier(db)
    w40 = make_item(db, "Ne 40/1", "Raw White")
    w30 = make_item(db, "Ne 30/1", "Raw White")
    make_batch(db, sup, w40, 70)
    make_batch(db, sup, w30, 10)
    db.commit()
    return {"sup": sup, "w40": w40, "w30": w30, "fabric": dyed_fabric, "buyer": buyer}


def order_body(stocked, **over):
    body = {
        "buyer_id": stocked["buyer"].id,
        "fabric_type_id": stocked["fabric"].id,
        "colour": "Maroon",
        "qty_m": "500",
        "rate_paise_per_m": 24000,
        "deadline": str(date.today() + timedelta(days=30)),
    }
    return {**body, **over}


def test_preview_uses_raw_white_for_dyed_fabric(api, stocked):
    res = api(
        Role.accounts,
        "POST",
        "/api/orders/requirement-preview",
        json={"fabric_type_id": stocked["fabric"].id, "colour": "Maroon", "qty_m": "500"},
    )
    assert res.status_code == 200, res.text
    # 500 m x 1.5 m x 120 g / 1000 / 0.9 = 100 kg, split 60 / 40, both Raw White
    assert [
        (x["count"], x["colour"], x["kg_needed"], x["kg_free"], x["kg_short"]) for x in res.json()
    ] == [
        ("Ne 40/1", "Raw White", "60.000", "70.000", "0.000"),
        ("Ne 30/1", "Raw White", "40.000", "10.000", "30.000"),
    ]


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"deadline": str(date.today())}, "deadline"),
        ({"qty_m": "0"}, "qty_m"),
        ({"colour": "   "}, "colour"),
        ({"rate_paise_per_m": 0}, "rate_paise_per_m"),
        ({"qty_m": "12.3456"}, "qty_m"),
    ],
)
def test_order_input_validation(api, stocked, over, field):
    res = api(Role.accounts, "POST", "/api/orders", json=order_body(stocked, **over))
    assert res.status_code == 422
    assert res.json()["error"]["field"] == field


def test_confirm_plans_work_orders_reserves_and_lists_shortfall(api, db, stocked):
    created = api(Role.accounts, "POST", "/api/orders", json=order_body(stocked))
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["code"].startswith("SO-") and order["status"] == "draft"
    assert order["buyer"]["name"] == "Test Buyer"

    res = api(Role.accounts, "POST", f"/api/orders/{order['id']}/confirm")
    assert res.status_code == 200, res.text
    alloc = res.json()
    assert [(x["kg_reserved"], x["kg_short"]) for x in alloc["lines"]] == [
        ("60.000", "0.000"),
        ("10.000", "30.000"),
    ]
    assert alloc["fully_covered"] is False
    wos = db.scalars(select(WorkOrder).where(WorkOrder.order_id == order["id"])).all()
    assert [w.stage for w in wos] == ["weaving", "dyeing"]

    to_buy = api(Role.accounts, "GET", "/api/orders/to-buy").json()
    row = next(r for r in to_buy if r["order_id"] == order["id"])
    assert (row["label"], row["to_buy_kg"]) == ("Cotton Ne 30/1 Raw White", "30.000")
    assert row["suggested_supplier_id"] == stocked["sup"].id

    # one click: the shortfall becomes an expected delivery, and leaves the to-buy list
    ed = api(
        Role.accounts,
        "POST",
        "/api/inventory/expected-deliveries",
        json={
            "supplier_id": row["suggested_supplier_id"],
            "yarn_item_id": row["yarn_item_id"],
            "expected_kg": row["to_buy_kg"],
            "rate_paise_per_kg": row["suggested_rate_paise_per_kg"],
            "expected_date": str(date.today() + timedelta(days=3)),
            "order_id": order["id"],
        },
    )
    assert ed.status_code == 201, ed.text
    after = api(Role.accounts, "GET", "/api/orders/to-buy").json()
    row = next(r for r in after if r["order_id"] == order["id"])
    assert (row["on_order_kg"], row["to_buy_kg"]) == ("30.000", "0.000")

    again = api(Role.accounts, "POST", f"/api/orders/{order['id']}/confirm")
    assert again.status_code == 409 and again.json()["error"]["code"] == "illegal_transition"


def test_cancel_releases_reservations(api, db, stocked):
    order = api(Role.accounts, "POST", "/api/orders", json=order_body(stocked)).json()
    api(Role.accounts, "POST", f"/api/orders/{order['id']}/confirm")
    assert inv.free_stock(db, stocked["w40"].id) == D(10)
    res = api(
        Role.accounts,
        "POST",
        f"/api/orders/{order['id']}/cancel",
        json={"reason": "Buyer cancelled"},
    )
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert inv.free_stock(db, stocked["w40"].id) == D(70)


def test_reserve_again_picks_up_new_stock(api, db, stocked):
    order = api(Role.accounts, "POST", "/api/orders", json=order_body(stocked)).json()
    api(Role.accounts, "POST", f"/api/orders/{order['id']}/confirm")
    make_batch(db, stocked["sup"], stocked["w30"], 50)
    db.commit()
    alloc = api(Role.accounts, "POST", f"/api/orders/{order['id']}/reserve").json()
    assert alloc["fully_covered"] is True
    assert alloc["lines"][1]["mixed_lots"] is True  # 10 kg lot + 30 kg from the new one


def test_to_buy_counts_free_stock_once_earliest_deadline_first(db, stocked, buyer):
    fabric = plain_fabric(db)  # 100% Ne 40/1, order colour kept
    w40 = stocked["w40"]  # 70 kg free
    late = make_order(db, buyer, fabric, "Raw White", 250)  # 50 kg
    late.deadline = date.today() + timedelta(days=40)
    soon = make_order(db, buyer, fabric, "Raw White", 250)  # 50 kg
    soon.deadline = date.today() + timedelta(days=10)
    db.flush()
    rows = {r["order_id"]: r for r in inv.to_buy(db) if r["yarn_item_id"] == w40.id}
    assert (rows[soon.id]["free_cover_kg"], rows[soon.id]["to_buy_kg"]) == (D(50), D(0))
    assert (rows[late.id]["free_cover_kg"], rows[late.id]["to_buy_kg"]) == (D(20), D(30))


def test_order_role_checks(api, stocked):
    assert api(Role.qc, "POST", "/api/orders", json=order_body(stocked)).status_code == 403
    assert api(Role.store, "POST", "/api/orders", json=order_body(stocked)).status_code == 403
    order = api(Role.owner, "POST", "/api/orders", json=order_body(stocked)).json()
    assert api(Role.store, "POST", f"/api/orders/{order['id']}/confirm").status_code == 403
    assert api(Role.qc, "GET", "/api/orders/to-buy").status_code == 403
    assert api(Role.dispatch, "GET", f"/api/orders/{order['id']}/allocation").status_code == 200


# Two sessions reserve the same 100 kg lot at the same moment, on real separate connections.
# FOR UPDATE makes the second wait; it then sees the first one's reservation. Total stays 100.
def test_concurrent_reservations_never_share_kilos(engine, monkeypatch):
    ids = {}
    with Session(engine) as db:
        ensure_locations(db)
        sup = make_supplier(db, "TCONC")
        item = YarnItem(fibre="ConcFibre", count="Ne 20/1", colour="Grey")
        db.add(item)
        db.flush()
        fabric = plain_fabric(db, count_="Ne 20/1", fibre="ConcFibre", code="TCONC")
        buyer = Buyer(code="TCONC", name="Conc Buyer", gstin="29AAGFG9753P1Z9")
        db.add(buyer)
        db.flush()
        batch = make_batch(db, sup, item, 100)
        orders = [make_order(db, buyer, fabric, "Grey", 400) for _ in range(2)]  # 80 kg each
        db.commit()
        ids = {
            "batch": batch.id,
            "orders": [o.id for o in orders],
            "item": item.id,
            "fabric": fabric.id,
            "buyer": buyer.id,
            "receipt": batch.receipt_id,
            "sup": sup.id,
        }

    # slow down the gap between reading free stock and writing the reservation, so without the
    # row lock both sessions would read 100 kg free and both reserve 80 kg
    real_pick = inv.pick_lots

    def slow_pick(need, lots):
        time.sleep(0.5)
        return real_pick(need, lots)

    monkeypatch.setattr(inv, "pick_lots", slow_pick)
    start = threading.Barrier(2)
    errors = []

    def worker(order_id):
        try:
            with Session(engine) as db:
                start.wait()
                inv.reserve(db, order_id, None)
                db.commit()
        except Exception as e:  # surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(o,)) for o in ids["orders"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    try:
        assert errors == []
        with Session(engine) as db:
            total = db.scalar(
                select(func.sum(Reservation.kg)).where(
                    Reservation.yarn_batch_id == ids["batch"],
                    Reservation.status == ReservationStatus.active,
                )
            )
            assert total == D(100)
            per_order = sorted(
                db.scalars(
                    select(Reservation.kg).where(Reservation.yarn_batch_id == ids["batch"])
                ).all()
            )
            assert per_order == [D(20), D(80)]
    finally:
        with Session(engine) as db:
            res_ids = db.scalars(
                select(Reservation.id).where(Reservation.order_id.in_(ids["orders"]))
            ).all()
            db.execute(
                delete(AuditLog).where(
                    AuditLog.entity_type == "reservations", AuditLog.entity_id.in_(res_ids)
                )
            )
            db.execute(delete(Reservation).where(Reservation.order_id.in_(ids["orders"])))
            db.execute(delete(StockMove).where(StockMove.yarn_batch_id == ids["batch"]))
            db.execute(delete(YarnBatch).where(YarnBatch.id == ids["batch"]))
            db.execute(delete(Receipt).where(Receipt.id == ids["receipt"]))
            db.execute(delete(ExpectedDelivery).where(ExpectedDelivery.yarn_item_id == ids["item"]))
            db.execute(delete(Order).where(Order.id.in_(ids["orders"])))
            db.execute(delete(FabricRecipe).where(FabricRecipe.fabric_type_id == ids["fabric"]))
            db.execute(
                delete(FabricTypeStage).where(FabricTypeStage.fabric_type_id == ids["fabric"])
            )
            db.execute(delete(FabricType).where(FabricType.id == ids["fabric"]))
            db.execute(delete(Buyer).where(Buyer.id == ids["buyer"]))
            db.execute(delete(YarnItem).where(YarnItem.id == ids["item"]))
            db.commit()
