import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.deps import COOKIE_NAME
from app.modules.auth.models import Role
from tests.conftest import PASSWORD


def test_login_sets_cookie_and_me_works(client, make_user):
    make_user(Role.store)
    res = client.post("/api/auth/login", json={"email": " Store@Test.local ", "password": PASSWORD})
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["role"] == "store"
    assert body["access_token"]
    assert COOKIE_NAME in res.cookies
    assert "httponly" in res.headers["set-cookie"].lower()

    me = client.get("/api/auth/me")  # cookie only, no header
    assert me.status_code == 200
    assert me.json()["email"] == "store@test.local"


def test_wrong_password_is_401_in_error_shape(client, make_user):
    make_user(Role.qc)
    res = client.post("/api/auth/login", json={"email": "qc@test.local", "password": "nope"})
    assert res.status_code == 401
    assert res.json() == {
        "error": {"code": "unauthorized", "message": "Wrong email or password", "field": "password"}
    }


def test_inactive_user_cannot_log_in(client, make_user):
    make_user(Role.accounts, active=False)
    res = client.post(
        "/api/auth/login", json={"email": "accounts@test.local", "password": PASSWORD}
    )
    assert res.status_code == 401


def test_no_token_is_401(client):
    res = client.get("/api/orders")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_wrong_role_is_403(client_as):
    store = client_as(Role.store)
    res = store.post("/api/masters/suppliers", json={"code": "X1", "name": "X"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"
    assert store.get("/api/finance/invoices").status_code == 403


def test_owner_passes_every_role_check(client_as):
    owner = client_as(Role.owner)
    assert owner.get("/api/finance/invoices").status_code == 200
    assert owner.get("/api/workforce/attendance").status_code == 200


# accounts is one desk: buyer orders and the books
def test_accounts_takes_orders_and_keeps_books(client_as):
    desk = client_as(Role.accounts)
    assert desk.get("/api/orders/to-buy").status_code == 200
    assert desk.get("/api/finance/invoices").status_code == 200
    assert client_as(Role.store).get("/api/finance/invoices").status_code == 403


# 0002 moves old sales users to accounts, then the check refuses "sales"
def test_migration_merges_sales_into_accounts(engine):
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    command.downgrade(cfg, "0001")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES ('Old desk', 'old-sales@test.local', 'x', 'sales')"
                )
            )
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            role = conn.scalar(text("SELECT role FROM users WHERE email = 'old-sales@test.local'"))
            conn.execute(text("DELETE FROM users WHERE email = 'old-sales@test.local'"))
        assert role == "accounts"
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (name, email, password_hash, role) "
                    "VALUES ('New desk', 'new-sales@test.local', 'x', 'sales')"
                )
            )
    finally:
        command.upgrade(cfg, "head")
