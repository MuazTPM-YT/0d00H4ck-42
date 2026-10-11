from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.enums import Source, Stage, Unit
from app.modules.analytics import forecast, service
from app.modules.analytics.forecast import FloorMachine, Job
from app.modules.auth.models import Role
from app.modules.orders.models import OrderStatus
from app.modules.production.models import MachineEvent, MachineStatus, ProductionLog
from app.modules.quality.models import Roll, RollStatus
from tests.floor import build_floor

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
H = timedelta(hours=1)


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


# worked by hand: L1 10 m/h, L2 20 m/h. P runs on L1 (20 m = 2 h). L2 is down for 2 h.
# Both free at +2h, tie goes to L1 by code. EDF: B (11 Oct) -> L1 +2..+6,
# A (12 Oct) -> L2 +2..+7, C (15 Oct) -> L1 +6..+12. A's dyeing waits for its weaving: +7..+9.
def test_schedule_takes_earliest_free_machine_and_earliest_deadline():
    l1 = FloorMachine(1, "L1", Stage.weaving, 10, NOW)
    l2 = FloorMachine(2, "L2", Stage.weaving, 20, NOW + 2 * H)
    d1 = FloorMachine(3, "D1", Stage.dyeing, 50, NOW)
    jobs = {
        "P": Job(10, "P", 100, Stage.weaving, 20, "m", date(2026, 10, 20), machine_id=1),
        "A": Job(11, "A", 101, Stage.weaving, 100, "m", date(2026, 10, 12)),
        "B": Job(12, "B", 102, Stage.weaving, 40, "m", date(2026, 10, 11)),
        "C": Job(13, "C", 103, Stage.weaving, 60, "m", date(2026, 10, 15)),
        "A-dye": Job(14, "A-dye", 101, Stage.dyeing, 100, "m", date(2026, 10, 12)),
    }
    ready = forecast.schedule([l1, l2, d1], list(jobs.values()), NOW)

    plan = {k: (j.plan["machine"].code, j.plan["start"], j.plan["end"]) for k, j in jobs.items()}
    assert plan == {
        "P": ("L1", NOW, NOW + 2 * H),
        "B": ("L1", NOW + 2 * H, NOW + 6 * H),
        "A": ("L2", NOW + 2 * H, NOW + 7 * H),
        "C": ("L1", NOW + 6 * H, NOW + 12 * H),
        "A-dye": ("D1", NOW + 7 * H, NOW + 9 * H),
    }
    assert ready == {100: NOW + 2 * H, 101: NOW + 9 * H, 102: NOW + 6 * H, 103: NOW + 12 * H}


def test_job_with_no_machine_for_its_stage_stays_unplanned():
    job = Job(1, "X", 1, Stage.spinning, 10, "kg", date(2026, 10, 12))
    forecast.schedule([FloorMachine(1, "L1", Stage.weaving, 10, NOW)], [job], NOW)
    assert job.plan == {}


# deadline 11 Oct ends at 12 Oct 00:00 IST = 11 Oct 18:30 UTC
def test_status_against_end_of_deadline_day():
    deadline = date(2026, 10, 11)
    assert forecast.status_for(datetime(2026, 10, 11, 18, 31, tzinfo=UTC), deadline)[0] == "late"
    assert forecast.status_for(datetime(2026, 10, 11, 0, 0, tzinfo=UTC), deadline) == (
        "at_risk",
        18.5,
    )
    assert forecast.status_for(datetime(2026, 10, 10, 0, 0, tzinfo=UTC), deadline)[0] == "on_track"


# shift TA is 06:00-14:00 IST = 00:30-08:30 UTC; 8 running hours per shift
def run_loom_for_shifts(db, floor, metres_per_shift: list[int]) -> datetime:
    now = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    shift_start = datetime(2026, 10, 10, 0, 30, tzinfo=UTC)  # TA today, ends 08:30
    db.add(
        MachineEvent(
            machine_id=floor.loom1.id,
            at=now - timedelta(days=6),
            status=MachineStatus.running,
            source=Source.machine,
        )
    )
    for i, metres in enumerate(metres_per_shift):
        start = shift_start - 8 * H * i
        db.add(
            ProductionLog(
                work_order_id=floor.dyed_weave.id,
                machine_id=floor.loom1.id,
                shift_id=floor.shifts[0].id,
                qty=Decimal(metres),
                unit=Unit.m,
                at=start + 4 * H,
            )
        )
    db.commit()
    return now


def test_throughput_is_median_of_last_six_full_shifts(db, floor):
    # newest first: 10, 10, 20, 10, 5, 10 m/h; the 7th (100 m/h) is too old to count
    now = run_loom_for_shifts(db, floor, [80, 80, 160, 80, 40, 80, 800])
    rates = forecast.throughputs(db, now)
    assert rates[floor.loom1.id] == {"per_hour": 10.0, "from": "median of 6 shifts"}
    assert rates[floor.loom2.id] == {"per_hour": 18.0, "from": "rated speed"}


def test_breakdown_pushes_the_forecast_later(db, floor):
    now = run_loom_for_shifts(db, floor, [80] * 6)
    before = service.delivery_estimate(db, floor.shirt_order.id, now)
    for loom in (floor.loom1, floor.loom2):
        db.add(
            MachineEvent(
                machine_id=loom.id,
                at=now - H,
                status=MachineStatus.breakdown,
                reason="Warp beam snapped",
                source=Source.machine,
            )
        )
    db.commit()
    after = service.delivery_estimate(db, floor.shirt_order.id, now)
    assert after["expected_at"] > before["expected_at"]
    assert after["basis"]["qc_hours"] == forecast.QC_HOURS


def test_delivery_estimate_api_roles_and_closed_orders(client_as, db, floor):
    path = f"/api/analytics/orders/{floor.shirt_order.id}/delivery-estimate"
    assert client_as(Role.qc).get(path).status_code == 403

    body = client_as(Role.accounts).get(path).json()
    assert body["order_code"] == "SO-T1"
    assert body["status"] in {"on_track", "at_risk", "late"}
    assert body["stages"][0]["remaining"] == float(floor.shirt_weave.planned_qty)
    assert "LM-T" in next(iter(body["basis"]["throughputs"]))

    floor.shirt_order.status = OrderStatus.closed
    db.commit()
    res = client_as(Role.supervisor).get(path)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_forecastable"


def test_delivery_board_lists_most_urgent_first(client_as, floor):
    rows = client_as(Role.accounts).get("/api/analytics/delivery").json()
    assert {r["order_code"] for r in rows} == {"SO-T1", "SO-T2"}
    ranks = [forecast_rank(r) for r in rows]
    assert ranks == sorted(ranks)


def forecast_rank(row: dict) -> tuple:
    return (service.RISK_ORDER[row["status"]], row["slack_hours"] or 0)


# running shifts with no logs give a 0 m/h median: a data gap, not a dead loom, keep rated speed
def test_zero_median_falls_back_to_rated_speed(db, floor):
    now = run_loom_for_shifts(db, floor, [80])
    rates = forecast.throughputs(db, now)
    assert rates[floor.loom1.id] == {"per_hour": 18.0, "from": "rated speed"}


# a job that already made its planned qty is done, whatever its status says
def test_job_with_nothing_left_counts_as_done(db, floor):
    db.add(
        ProductionLog(
            work_order_id=floor.shirt_weave.id,
            machine_id=floor.loom1.id,
            shift_id=floor.shifts[0].id,
            qty=floor.shirt_weave.planned_qty,
            unit=Unit.m,
            at=NOW - H,
        )
    )
    db.commit()
    assert service.delivery_estimate(db, floor.shirt_order.id, NOW)["stages"] == []


# 98% shipped = done: no risk, no date, and its leftover job takes no loom time
def test_shipped_order_is_not_forecast(db, floor):
    db.add(
        Roll(
            code="R-TS1",
            order_id=floor.shirt_order.id,
            work_order_id=floor.shirt_weave.id,
            loom_machine_id=floor.loom1.id,
            shift_id=floor.shifts[0].id,
            length_m=Decimal(590),
            status=RollStatus.dispatched,
            shade_band="A",
            passed_at=NOW - H,
            location_id=floor.loc["wip"].id,
        )
    )
    db.commit()
    est = service.delivery_estimate(db, floor.shirt_order.id, NOW)
    assert (est["status"], est["expected_at"], est["stages"]) == ("on_track", None, [])


# planned = order x 1.05 waste allowance: once the order's own metres are woven, nothing is left
def test_stage_done_once_order_metres_are_made(db, floor):
    db.add(
        ProductionLog(
            work_order_id=floor.shirt_weave.id,
            machine_id=floor.loom1.id,
            shift_id=floor.shifts[0].id,
            qty=floor.shirt_order.qty_m,
            unit=Unit.m,
            at=NOW - H,
        )
    )
    db.commit()
    assert floor.shirt_weave.planned_qty > floor.shirt_order.qty_m
    assert service.delivery_estimate(db, floor.shirt_order.id, NOW)["stages"] == []
