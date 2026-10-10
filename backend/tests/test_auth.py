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
    make_user(Role.sales, active=False)
    res = client.post("/api/auth/login", json={"email": "sales@test.local", "password": PASSWORD})
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
