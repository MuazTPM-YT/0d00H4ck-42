import hmac
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.errors import AppError
from app.modules.auth.models import Role
from app.modules.dispatch import service
from app.modules.dispatch.models import Dispatch, DispatchStatus
from tests.mill import Mill


@pytest.fixture
def mill(db):
    return Mill(db)


# a truck that really left: rolls scanned on, confirmed by the clerk through the API
@pytest.fixture
def truck(db, mill, client_as):
    return send_truck(db, mill, client_as, 300)


# 190 m of rolls leave on one truck for an order of order_m
def send_truck(db, mill, client_as, order_m):
    o = mill.order(order_m)
    wo = mill.work_order(o)
    rolls = [mill.roll(wo, 100), mill.roll(wo, 90)]
    d = Dispatch(
        code=f"DN-D{o.id}",
        order_id=o.id,
        buyer_id=o.buyer_id,
        vehicle_no="KA-01-AB-1234",
        driver="Ravi",
    )
    db.add(d)
    db.commit()
    clerk = client_as(Role.dispatch)
    for r in rolls:
        res = clerk.post(f"/api/dispatch/dispatches/{d.id}/scan", json={"roll_code": r.code})
        assert res.status_code == 200, res.text
    assert clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm").status_code == 200
    db.refresh(d)
    return d, o, clerk


def give(client, d, otp, who="Meena, stores"):
    return client.post(f"/api/deliver/{d.delivery_token}", json={"otp": otp, "received_by": who})


def wrong(otp: str) -> str:
    return f"{(int(otp) + 1) % 10**6:06d}"


def test_confirm_opens_driver_link_and_code_seen_by_buyer_only(client_as, truck):
    d, o, clerk = truck
    assert d.delivery_otp and len(d.delivery_otp) == 6 and d.delivery_otp.isdigit()
    detail = clerk.get(f"/api/dispatch/dispatches/{d.id}")
    assert detail.json()["delivery_token"] == d.delivery_token
    assert detail.json()["has_code"] and detail.json()["tries_left"] == 5
    assert d.delivery_otp not in detail.text
    accounts = client_as(Role.accounts)
    office = accounts.get(f"/api/track/orders/{o.id}")
    assert office.status_code == 200 and d.delivery_otp not in office.text

    buyer = accounts.get(f"/api/track/{o.tracking_token}").json()
    (truck_row,) = buyer["deliveries"]
    assert truck_row["code"] == d.delivery_otp and truck_row["delivered_at"] is None


def test_driver_page_lists_rolls_without_code_or_money(client, truck):
    d, _, _ = truck
    res = client.get(f"/api/deliver/{d.delivery_token}")
    assert res.status_code == 200
    body = res.json()
    assert body["challan"] == d.code and body["roll_count"] == 2 and body["metres"] == "190.000"
    assert d.delivery_otp not in res.text
    assert not any("paise" in k or "rate" in k for k in body)


def test_truck_still_at_the_mill_has_no_driver_page(client, db, mill):
    o = mill.order()
    d = Dispatch(code="DN-DRAFT", order_id=o.id, buyer_id=o.buyer_id)
    db.add(d)
    db.commit()
    assert client.get(f"/api/deliver/{d.delivery_token}").status_code == 404
    assert give(client, d, "123456").status_code == 404
    assert client.get("/api/deliver/not-a-real-token-at-all").status_code == 404


def test_right_code_delivers_once_and_buyer_sees_it(client, client_as, db, truck):
    d, o, _ = truck
    res = give(client, d, d.delivery_otp)
    assert res.status_code == 200, res.text
    assert res.json()["delivered_at"] and res.json()["received_by"] == "Meena, stores"
    first = res.json()["delivered_at"]

    # flaky network: the driver taps again, even with a typo; nothing changes
    again = give(client, d, wrong(d.delivery_otp), who="Someone else")
    assert again.status_code == 200 and again.json()["delivered_at"] == first
    assert again.json()["received_by"] == "Meena, stores"

    buyer = client.get(f"/api/track/{o.tracking_token}").json()
    (row,) = buyer["deliveries"]
    assert row["delivered_at"] and row["code"] is None and row["received_by"] == "Meena, stores"
    assert any(e["title"] == "Delivered, received by Meena, stores" for e in buyer["timeline"])
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "delivered")).all()
    assert len(audit) == 1 and audit[0].user_id is None and audit[0].data["via"] == "driver_link"


def test_five_wrong_codes_lock_until_the_office_issues_a_new_one(client, db, truck):
    d, o, clerk = truck
    bad = wrong(d.delivery_otp)
    for left in (4, 3, 2, 1):
        res = give(client, d, bad)
        assert res.status_code == 422 and res.json()["error"]["code"] == "wrong_otp"
        assert res.json()["error"]["field"] == "otp"
        assert f"{left} tr" in res.json()["error"]["message"]
    assert "locked" in give(client, d, bad).json()["error"]["message"]

    # locked: even the right code is refused now, and the buyer link stops showing it
    locked = give(client, d, d.delivery_otp)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "otp_locked"
    (row,) = client.get(f"/api/track/{o.tracking_token}").json()["deliveries"]
    assert row["code"] is None and row["code_locked"] is True

    old = d.delivery_otp
    fresh = clerk.post(f"/api/dispatch/dispatches/{d.id}/new-code")
    assert fresh.status_code == 200 and fresh.json()["tries_left"] == 5
    db.refresh(d)
    (row,) = client.get(f"/api/track/{o.tracking_token}").json()["deliveries"]
    assert row["code"] == d.delivery_otp and row["code_locked"] is False
    if d.delivery_otp != old:
        assert give(client, d, old).status_code == 422
    assert give(client, d, d.delivery_otp).status_code == 200


def test_office_types_the_code_when_driver_has_no_signal(client_as, db, truck):
    d, _, clerk = truck
    url = f"/api/dispatch/dispatches/{d.id}/deliver"
    body = {"otp": d.delivery_otp, "received_by": "Gate security", "note": "1 roll edge wet"}
    clerk_auth = clerk.headers["Authorization"]
    assert client_as(Role.accounts).post(url, json=body).status_code == 403
    clerk.headers["Authorization"] = clerk_auth
    res = clerk.post(url, json=body)
    assert res.status_code == 200, res.text
    assert res.json()["delivered_at"] and res.json()["delivery_note"] == "1 roll edge wet"
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "delivered"))
    assert audit.user_id is not None and audit.data["via"] == "office_phone"
    assert clerk.post(f"/api/dispatch/dispatches/{d.id}/new-code").json()["error"]["code"] == (
        "delivered"
    )


def test_new_code_and_office_delivery_need_a_truck_that_left(client_as, db, mill):
    o = mill.order()
    d = Dispatch(code="DN-YARD", order_id=o.id, buyer_id=o.buyer_id)
    db.add(d)
    db.commit()
    clerk = client_as(Role.dispatch)
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/new-code")
    assert res.status_code == 409 and res.json()["error"]["code"] == "not_left"
    body = {"otp": "123456", "received_by": "X"}
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/deliver", json=body)
    assert res.status_code == 409 and res.json()["error"]["code"] == "not_left"


def test_bad_code_or_blank_receiver_is_rejected(client, truck):
    d, _, _ = truck
    for otp in ("12ab56", "12345", "1234567", ""):
        res = give(client, d, otp)
        assert res.status_code == 422 and res.json()["error"]["field"] == "otp"
    res = give(client, d, d.delivery_otp, who="   ")
    assert res.status_code == 422 and res.json()["error"]["field"] == "received_by"


# two phones guessing at the same moment cannot both spend the last try
def test_last_try_cannot_be_spent_twice(committed, monkeypatch):
    with Session(committed) as s:
        mill = Mill(s)
        o = mill.order()
        d = Dispatch(
            code="DN-RACE",
            order_id=o.id,
            buyer_id=o.buyer_id,
            vehicle_no="KA01AB1",
            status=DispatchStatus.confirmed,
            confirmed_at=datetime.now(UTC),
            delivery_otp="111111",
            otp_tries=4,
        )
        s.add(d)
        s.commit()
        token, d_id = d.delivery_token, d.id

    # slow check: without the row lock both guesses would read 4 tries and both get a go
    def slow(a, b):
        time.sleep(0.3)
        return hmac.compare_digest(a, b)

    monkeypatch.setattr(service, "hmac", SimpleNamespace(compare_digest=slow))
    barrier = threading.Barrier(2)
    outcomes = []

    def guess():
        with Session(committed) as s:
            barrier.wait()
            try:
                service.deliver(s, token, {"otp": "222222", "received_by": "X"})
                outcomes.append("ok")
            except AppError as e:
                outcomes.append(e.code)

    threads = [threading.Thread(target=guess) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["otp_locked", "wrong_otp"]
    with Session(committed) as s:
        assert s.get(Dispatch, d_id).otp_tries == 5


def test_stage_turns_delivered_once_the_last_truck_code_is_entered(client, db, mill, client_as):
    d, o, _ = send_truck(db, mill, client_as, 190)
    assert client.get(f"/api/track/{o.tracking_token}").json()["stage"] == "shipped"
    assert give(client, d, d.delivery_otp).status_code == 200
    assert client.get(f"/api/track/{o.tracking_token}").json()["stage"] == "delivered"


def test_part_order_delivered_is_still_partly_shipped(client, truck):
    d, o, _ = truck
    assert give(client, d, d.delivery_otp).status_code == 200
    assert client.get(f"/api/track/{o.tracking_token}").json()["stage"] == "partly_shipped"
