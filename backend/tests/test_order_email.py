import smtplib

import pytest

from app.core import mail
from app.core.config import get_settings
from app.modules.auth.models import Role
from app.modules.masters.models import Buyer
from app.modules.orders.models import Order, OrderStatus
from tests.mill import Mill


@pytest.fixture
def draft(db):
    mill = Mill(db)
    mill.buyer.email = "buyer@test.local"
    order = mill.order(status=OrderStatus.draft)
    db.commit()
    return order


def confirm(client_as, order):
    res = client_as(Role.accounts).post(f"/api/orders/{order.id}/confirm")
    assert res.status_code == 200, res.text
    return res


def test_confirm_emails_the_buyer_their_tracking_link(client_as, client, draft, outbox):
    confirm(client_as, draft)
    ((to, subject, body),) = outbox
    assert to == "buyer@test.local" and draft.code in subject
    assert f"http://mill.test/track/{draft.tracking_token}" in body
    view = client.get(f"/api/track/orders/{draft.id}").json()
    assert view["mail_on"] is True
    # the office page shows the very link the buyer got, not the clerk's localhost
    assert view["tracking_url"] == f"http://mill.test/track/{draft.tracking_token}"
    assert view["link_email"]["status"] == "sent" and view["link_email"]["to"] == to


def test_buyer_without_email_is_skipped_and_said_so(client_as, client, db, draft, outbox):
    db.get(Buyer, draft.buyer_id).email = None
    db.commit()
    confirm(client_as, draft)
    assert outbox == []
    email = client.get(f"/api/track/orders/{draft.id}").json()["link_email"]
    assert email["status"] == "skipped" and "no email" in email["error"]


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted"), "app pass"),
        (TimeoutError("timed out"), "did not answer in time"),
        (ConnectionRefusedError("refused"), "Cannot reach"),
    ],
)
def test_mail_failure_never_undoes_the_confirm(
    client_as, client, db, draft, outbox, monkeypatch, error, says
):
    def fail(*_):
        raise error

    monkeypatch.setattr(mail, "send", fail)
    confirm(client_as, draft)
    db.expire_all()
    assert db.get(Order, draft.id).status == OrderStatus.confirmed
    email = client.get(f"/api/track/orders/{draft.id}").json()["link_email"]
    assert email["status"] == "failed" and says in email["error"]


def test_resend_uses_the_current_link(client_as, client, db, draft, outbox):
    confirm(client_as, draft)
    dispatch = client_as(Role.dispatch)
    url = f"/api/track/orders/{draft.id}/email-link"
    assert dispatch.post(url).status_code == 403
    owner = client_as(Role.owner)
    owner.post(f"/api/track/orders/{draft.id}/rotate-token")
    db.refresh(draft)
    res = owner.post(url)
    assert res.status_code == 200 and res.json()["link_email"]["status"] == "sent"
    assert len(outbox) == 2 and f"/track/{draft.tracking_token}" in outbox[1][2]


def test_mail_off_sends_nothing_and_resend_says_why(client_as, client, draft):
    confirm(client_as, draft)
    view = client.get(f"/api/track/orders/{draft.id}").json()
    assert view["mail_on"] is False and view["link_email"] is None
    res = client.post(f"/api/track/orders/{draft.id}/email-link")
    assert res.status_code == 409 and res.json()["error"]["code"] == "mail_off"


# SMTP_HOST set but the login or link base missing: stop at startup and name the keys
def test_half_set_mail_config_fails_loud(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    for key in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "WEB_URL"):
        monkeypatch.setenv(key, "")
    with pytest.raises(SystemExit) as stop:
        get_settings.__wrapped__()
    assert "SMTP_PASSWORD" in str(stop.value) and "WEB_URL" in str(stop.value)
