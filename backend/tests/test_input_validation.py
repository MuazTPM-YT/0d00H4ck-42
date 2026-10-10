from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.modules.auth.models import Role
from app.modules.dispatch.schemas import DispatchCreate
from app.modules.finance import schemas as finance_schemas
from app.modules.finance.schemas import ExpenseIn, PaymentIn, WageRunIn
from app.modules.inventory import schemas as inventory_schemas
from app.modules.inventory.schemas import ExpectedDeliveryIn, IssueIn, ReceiptLineIn, ReturnIn
from app.modules.masters.schemas import RecipeIn, YarnItemIn
from app.modules.orders import schemas as order_schemas
from app.modules.orders.schemas import OrderIn, RequirementIn
from app.modules.production.schemas import OutputIn, RollIn
from app.modules.quality.schemas import DefectIn, QcCheckIn


@pytest.mark.parametrize(
    "model,body,field",
    [
        (DispatchCreate, {"order_id": 0}, "order_id"),
        (
            PaymentIn,
            {"invoice_id": -1, "amount_paise": 100, "received_on": "2020-01-01", "mode": "cash"},
            "invoice_id",
        ),
        (RecipeIn, {"fibre": "Cotton", "count": "   ", "share_pct": "100"}, "count"),
    ],
)
def test_invalid_identifiers_and_blank_recipe(model, body, field):
    with pytest.raises(ValidationError) as error:
        model.model_validate(body)
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("value", ["-800", "0", "NaN", "Infinity", "1.0001", "1000000000000"])
@pytest.mark.parametrize(
    "model,body,field",
    [
        (
            ExpectedDeliveryIn,
            {
                "supplier_id": 1,
                "yarn_item_id": 1,
                "rate_paise_per_kg": 100,
                "expected_date": date.today() + timedelta(days=1),
            },
            "expected_kg",
        ),
        (ReceiptLineIn, {"label_missing": True}, "received_kg"),
        (IssueIn, {"work_order_id": 1, "yarn_batch_id": 1}, "kg"),
        (ReturnIn, {"work_order_id": 1, "yarn_batch_id": 1}, "kg"),
        (RequirementIn, {"fabric_type_id": 1, "colour": "White"}, "qty_m"),
        (OutputIn, {"machine_id": 1}, "qty"),
        (RollIn, {"work_order_id": 1}, "length_m"),
    ],
)
def test_invalid_quantities(model, body, field, value):
    with pytest.raises(ValidationError):
        model.model_validate({**body, field: value})


@pytest.mark.parametrize("value", [-1, 0, 10**12 + 1, "NaN", "1.5"])
def test_invalid_payment_amount(value):
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=1, amount_paise=value, received_on="2020-01-01", mode="cash")


def test_zero_reorder_and_historical_records_are_valid():
    assert YarnItemIn(fibre="Cotton", count="30", colour="White", reorder_level_kg=0)
    assert PaymentIn(invoice_id=1, amount_paise=1, received_on="2020-01-01", mode="cash")
    assert ExpenseIn(date="2020-01-01", category="other", amount_paise=1)
    assert WageRunIn(period_start="2020-01-01", period_end="2020-01-31")


@pytest.mark.parametrize("value", [-1, 0, 1000, 1.5])
def test_defect_count_bounds(value):
    with pytest.raises(ValidationError):
        DefectIn(type="hole", count=value)


@pytest.mark.parametrize("field", ["gsm", "width_cm"])
@pytest.mark.parametrize("value", ["-800", "0", "NaN", "Infinity", "1.001"])
def test_qc_measurement_bounds(field, value):
    with pytest.raises(ValidationError):
        QcCheckIn.model_validate({"decision": "pass", "shade_band": "A", field: value})


def test_mill_date_boundaries(monkeypatch):
    today = date(2026, 10, 11)
    for module in (inventory_schemas, order_schemas, finance_schemas):
        monkeypatch.setattr(module, "mill_today", lambda: today)
    delivery = dict(supplier_id=1, yarn_item_id=1, expected_kg="800", rate_paise_per_kg=100)
    assert ExpectedDeliveryIn(**delivery, expected_date=today)
    assert ExpectedDeliveryIn(**delivery, expected_date=today + timedelta(days=365))
    for day in (today - timedelta(days=1), today + timedelta(days=366)):
        with pytest.raises(ValidationError):
            ExpectedDeliveryIn(**delivery, expected_date=day)
    order = dict(buyer_id=1, fabric_type_id=1, colour="White", qty_m="800", rate_paise_per_m=100)
    assert OrderIn(**order, deadline=today + timedelta(days=1))
    assert OrderIn(**order, deadline=today + timedelta(days=730))
    for day in (today, today + timedelta(days=731)):
        with pytest.raises(ValidationError):
            OrderIn(**order, deadline=day)
    assert PaymentIn(invoice_id=1, amount_paise=100, received_on=today, mode="cash")
    with pytest.raises(ValidationError):
        PaymentIn(
            invoice_id=1, amount_paise=100, received_on=today + timedelta(days=1), mode="cash"
        )
    with pytest.raises(ValidationError):
        WageRunIn(period_start=today, period_end=today - timedelta(days=1))
    with pytest.raises(ValidationError):
        WageRunIn(period_start=today - timedelta(days=63), period_end=today)


def test_ist_midnight(monkeypatch):
    from datetime import UTC, datetime

    from app.core import dates

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 10, 20, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(dates, "datetime", Clock)
    assert dates.mill_today() == date(2026, 10, 11)


@pytest.mark.parametrize(
    "role,path,body",
    [
        (
            Role.store,
            "/inventory/expected-deliveries",
            {
                "supplier_id": 1,
                "yarn_item_id": 1,
                "expected_kg": "-800",
                "rate_paise_per_kg": 100,
                "expected_date": "2099-01-01",
            },
        ),
        (
            Role.accounts,
            "/orders",
            {
                "buyer_id": 1,
                "fabric_type_id": 1,
                "colour": "White",
                "qty_m": "-800",
                "rate_paise_per_m": 100,
                "deadline": "2099-01-01",
            },
        ),
        (Role.supervisor, "/production/output", {"machine_id": 1, "qty": "-800"}),
        (
            Role.qc,
            "/quality/rolls/1/checks",
            {"decision": "pass", "shade_band": "A", "gsm": "-800"},
        ),
        (Role.dispatch, "/dispatch/dispatches", {"order_id": -1}),
        (
            Role.owner,
            "/masters/yarn-items",
            {"fibre": "Cotton", "count": "30", "colour": "White", "reorder_level_kg": "-800"},
        ),
        (
            Role.accounts,
            "/finance/payments",
            {"invoice_id": 1, "amount_paise": -800, "received_on": "2020-01-01", "mode": "cash"},
        ),
    ],
)
def test_invalid_api_inputs_for_every_role(client_as, role, path, body):
    response = client_as(role).post("/api" + path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["field"]


def test_reversed_dispatch_date_range(client_as):
    response = client_as(Role.dispatch).get(
        "/api/dispatch/dispatches?date_from=2026-10-11&date_to=2026-10-10"
    )
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "date_to"
