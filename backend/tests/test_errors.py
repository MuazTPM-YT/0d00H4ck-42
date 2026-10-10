from app.modules.auth.models import Role

SUPPLIER = {"code": "ksm", "name": "Kaveri Spinning Mills", "gstin": "33aabck1234f1z5"}


def test_not_found_shape(client_as):
    res = client_as(Role.owner).get("/api/masters/suppliers/999999")
    assert res.status_code == 404
    assert set(res.json()["error"]) == {"code", "message", "field"}
    assert res.json()["error"]["code"] == "not_found"


def test_validation_shape_points_at_field(client_as):
    res = client_as(Role.owner).post("/api/masters/suppliers", json={**SUPPLIER, "name": "   "})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    assert res.json()["error"]["field"] == "name"


def test_bad_gstin_rejected(client_as):
    res = client_as(Role.owner).post("/api/masters/suppliers", json={**SUPPLIER, "gstin": "123"})
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "gstin"


def test_duplicate_is_409_with_field(client_as):
    owner = client_as(Role.owner)
    created = owner.post("/api/masters/suppliers", json=SUPPLIER)
    assert created.status_code == 201
    assert created.json()["code"] == "KSM"  # normalised to upper case
    dup = owner.post("/api/masters/suppliers", json={**SUPPLIER, "gstin": None})
    assert dup.status_code == 409
    assert dup.json()["error"] == {
        "code": "duplicate",
        "message": "A record with this value already exists",
        "field": "code",
    }


def test_stub_is_501_in_error_shape(client, db, buyer, dyed_fabric):
    from app.modules.orders.models import Order

    order = Order(
        code="SO-T1",
        buyer_id=buyer.id,
        fabric_type_id=dyed_fabric.id,
        colour="Red",
        qty_m=10,
        rate_paise_per_m=100,
        deadline="2026-12-01",
    )
    db.add(order)
    db.commit()
    res = client.get(f"/api/track/{order.tracking_token}")
    assert res.status_code == 501
    assert res.json()["error"]["code"] == "not_implemented"


def test_unknown_tracking_token_is_404(client):
    assert client.get("/api/track/not-a-real-token").status_code == 404


def test_illegal_transition_is_409():
    import pytest

    from app.core.errors import Conflict
    from app.core.states import check_transition
    from app.modules.quality.models import RollStatus
    from app.modules.quality.service import ROLL_TRANSITIONS

    check_transition(ROLL_TRANSITIONS, RollStatus.passed, RollStatus.dispatched)
    with pytest.raises(Conflict) as e:
        check_transition(ROLL_TRANSITIONS, RollStatus.rejected, RollStatus.dispatched)
    assert e.value.status == 409
    assert e.value.code == "illegal_transition"
