import pytest

from app.core import mail
from app.modules.auth.models import Role
from app.modules.dispatch.models import Dispatch, DispatchStatus
from tests.mill import Mill


# a loaded truck at the gate, not yet confirmed
@pytest.fixture
def loaded(db, client_as):
    mill = Mill(db)
    o = mill.order(300)
    wo = mill.work_order(o)
    rolls = [mill.roll(wo, 100), mill.roll(wo, 90)]
    d = Dispatch(
        code=f"DN-E{o.id}",
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
    return d, clerk


def set_vehicle(clerk, d, email):
    body = {"vehicle_no": d.vehicle_no, "driver": "Ravi", "driver_email": email}
    return clerk.put(f"/api/dispatch/dispatches/{d.id}/vehicle", json=body)


def confirm(clerk, d, db):
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/confirm")
    assert res.status_code == 200, res.text
    db.refresh(d)


def detail(clerk, d):
    return clerk.get(f"/api/dispatch/dispatches/{d.id}").json()


def test_truck_leaving_emails_the_driver_their_link_not_the_code(db, loaded, outbox):
    d, clerk = loaded
    assert set_vehicle(clerk, d, "ravi@roadline.in").status_code == 200
    confirm(clerk, d, db)
    ((to, subject, body),) = outbox
    assert to == "ravi@roadline.in" and d.code in subject
    assert f"http://mill.test/deliver/{d.delivery_token}" in body and "2 rolls, 190 m" in body
    assert d.delivery_otp not in body
    view = detail(clerk, d)
    sent = view["driver_mail"]
    assert sent["status"] == "sent" and sent["to"] == "ravi@roadline.in"
    assert view["delivery_url"] == f"http://mill.test/deliver/{d.delivery_token}"


def test_no_driver_email_is_skipped_then_sent_once_filled_in(db, loaded, outbox):
    d, clerk = loaded
    confirm(clerk, d, db)
    assert outbox == []
    assert detail(clerk, d)["driver_mail"]["status"] == "skipped"

    url = f"/api/dispatch/dispatches/{d.id}/email-driver"
    res = clerk.post(url, json={"driver_email": "late@roadline.in"})
    assert res.status_code == 200, res.text
    assert res.json()["driver_email"] == "late@roadline.in"
    assert res.json()["driver_mail"]["status"] == "sent" and outbox[0][0] == "late@roadline.in"


def test_send_failure_never_undoes_the_truck(db, loaded, outbox, monkeypatch):
    d, clerk = loaded

    def fail(*_):
        raise TimeoutError("timed out")

    monkeypatch.setattr(mail, "send", fail)
    set_vehicle(clerk, d, "ravi@roadline.in")
    confirm(clerk, d, db)
    assert d.status == DispatchStatus.confirmed
    tried = detail(clerk, d)["driver_mail"]
    assert tried["status"] == "failed" and "did not answer in time" in tried["error"]


def test_resend_rules(client_as, db, loaded, outbox):
    d, clerk = loaded
    url = f"/api/dispatch/dispatches/{d.id}/email-driver"
    res = clerk.post(url, json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "not_left"

    confirm(clerk, d, db)
    bad = clerk.post(url, json={"driver_email": "not-an-email"})
    assert bad.status_code == 422 and bad.json()["error"]["field"] == "driver_email"
    clerk_auth = clerk.headers["Authorization"]
    assert client_as(Role.accounts).post(url, json={}).status_code == 403
    clerk.headers["Authorization"] = clerk_auth

    give = {"otp": d.delivery_otp, "received_by": "Gate"}
    assert clerk.post(f"/api/deliver/{d.delivery_token}", json=give).status_code == 200
    res = clerk.post(url, json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "delivered"


def test_mail_off_sends_nothing_and_resend_says_why(db, loaded):
    d, clerk = loaded
    set_vehicle(clerk, d, "ravi@roadline.in")
    confirm(clerk, d, db)
    body = detail(clerk, d)
    assert body["mail_on"] is False and body["driver_mail"] is None
    res = clerk.post(f"/api/dispatch/dispatches/{d.id}/email-driver", json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "mail_off"


def test_bad_driver_email_on_the_vehicle_form_is_rejected(loaded):
    d, clerk = loaded
    res = set_vehicle(clerk, d, "ravi at driver")
    assert res.status_code == 422 and res.json()["error"]["field"] == "driver_email"
