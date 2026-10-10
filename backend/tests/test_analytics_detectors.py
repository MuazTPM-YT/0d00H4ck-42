from datetime import UTC, date, datetime, time, timedelta
from itertools import count

import pytest
from sqlalchemy import select

from app.modules.analytics import detectors, explainer, service
from app.modules.analytics.detectors import (
    Breakdown,
    CutRoll,
    Downtime,
    GateBatch,
    IdleSpell,
    Lot,
    MachineDays,
    OutputLog,
    QcRoll,
    YieldJob,
)
from app.modules.analytics.models import Insight
from app.modules.masters.models import Shift
from app.modules.production.models import MachineEvent, MachineStatus, ProductionLog
from app.modules.workforce.schemas import IST
from tests.floor import build_floor

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
ids = count(1)


def rolls(n, defective, loom=1, supplier=1, days_ago=1, defect="colour_mismatch") -> list[QcRoll]:
    return [
        QcRoll(
            id=(i := next(ids)),
            code=f"R-{i:06d}",
            at=NOW - timedelta(days=days_ago),
            defects={defect} if k < defective else set(),
            factors={
                "machine": {(loom, f"LM-0{loom}")},
                "shift": {(1, "A")},
                "weaver": set(),
                "fabric": {(1, "SHIRT40")},
                "yarn_batch": {(supplier * 10, f"YB-00000{supplier}")},
                "supplier": {(supplier, ["", "SLY", "KSM", "DCS"][supplier])},
            },
        )
        for k in range(n)
    ]


def narratives_cite_only_facts(found: list[dict]) -> bool:
    return all(
        explainer.numbers_ok(explainer.narrate(f["kind"], f["facts"]), f["facts"]) for f in found
    )


# SLY 6 of 40 per loom, others 2 of 40: expected 3 x 40 x 4/80 = 6, observed 18, lift 3.0
def test_supplier_fires_when_its_yarn_is_worse_on_the_same_looms():
    month = [
        r
        for loom in (1, 2, 3)
        for r in rolls(40, 6, loom, 1) + rolls(40, 2, loom, 2) + rolls(40, 2, loom, 3)
    ]
    (found,) = detectors.supplier_defects(month)
    assert found["entity_id"] == 1
    facts = found["facts"]
    assert (facts["defective"], facts["expected"], facts["lift"], facts["looms"]) == (
        18,
        6.0,
        3.0,
        3,
    )
    assert len([r for r in facts["records"] if r["type"] == "rolls"]) == 18
    assert {"type": "yarn_batches", "id": 10, "code": "YB-000001"} in facts["records"]
    assert narratives_cite_only_facts([found])


def test_supplier_silent_when_rates_match():
    month = [r for loom in (1, 2, 3) for s in (1, 2, 3) for r in rolls(40, 2, loom, s)]
    assert detectors.supplier_defects(month) == []


# SLY mostly runs on the bad loom 3. Pooled: 18% vs 8% looks guilty. Loom by loom: same rate.
def test_supplier_not_blamed_for_a_bad_loom():
    month = rolls(10, 0, 1, 1) + rolls(100, 2, 1, 2) + rolls(90, 18, 3, 1) + rolls(50, 10, 3, 2)
    s = detectors.supplier_lift(month, 1, "colour_mismatch")
    assert (s["defective"], s["expected"], s["lift"]) == (18, 18.2, 1.0)
    assert detectors.supplier_defects(month) == []


def gate(supplier_id, code, n, quarantined) -> list[GateBatch]:
    return [GateBatch(supplier_id, code, k < quarantined, False, next(ids), "YB") for k in range(n)]


def test_gate_quarantine_rate_fires_against_other_suppliers():
    (found,) = detectors.gate_problems(gate(1, "SLY", 6, 3) + gate(2, "KSM", 10, 1))
    assert found["facts"]["key"] == "gate_quarantined"
    assert (found["facts"]["rate_pct"], found["facts"]["others_rate_pct"]) == (50.0, 10.0)
    assert narratives_cite_only_facts([found])
    assert detectors.gate_problems(gate(1, "SLY", 6, 0) + gate(2, "KSM", 10, 1)) == []


# 300 rolls, 10 defective: baseline 3.3%
def three_weeks_at_three_pct() -> list[QcRoll]:
    return [r for d in range(8, 28, 2) for r in rolls(15, 0, 1, days_ago=d)] + [
        r for d in range(8, 28, 2) for r in rolls(15, 1, 2, days_ago=d)
    ]


# window 100 rolls, 17 defective; at 3.3% we expect 3.3, so 13.67 extra.
# LM-02: 15 defective, 1.67 expected -> 13.33 of the extra = 97.6%; 30% vs 4% = 7.5x
def test_root_cause_ranks_the_loom_behind_the_rise():
    window = rolls(50, 2, 1, days_ago=2) + rolls(50, 15, 2, days_ago=2)
    base = three_weeks_at_three_pct()
    assert len(base) == 300
    found = detectors.root_causes(base + window, NOW)
    assert (found["entity_type"], found["entity_id"]) == ("machines", 2)
    top = found["facts"]["causes"][0]
    assert (top["value"], top["share_pct"], top["lift"]) == ("LM-02", 97.6, 7.5)
    assert len(found["facts"]["records"]) == 15
    assert narratives_cite_only_facts([found])


def test_root_cause_silent_when_rate_is_flat():
    window = rolls(50, 1, 1, days_ago=2) + rolls(50, 2, 2, days_ago=2)
    assert detectors.root_causes(three_weeks_at_three_pct() + window, NOW) is None


def test_number_guard_rejects_a_number_not_in_the_facts():
    facts = {"lift": 2.8, "supplier": "SLY", "records": [{"id": 35}]}
    assert explainer.numbers_ok("SLY runs 2.8x higher.", facts)
    assert not explainer.numbers_ok("SLY runs 3x higher.", facts)
    assert not explainer.numbers_ok("See roll 35.", facts)


# --- machines

DAY0 = date(2026, 9, 10)


def steady(days: int, level: float = 17.0) -> list[tuple[date, float]]:
    # small day-to-day wobble, like a healthy loom
    return [(DAY0 + timedelta(days=d), level + (0.1 if d % 2 else -0.1)) for d in range(days)]


def machine(series, breakdowns=()) -> MachineDays:
    return MachineDays(3, "LM-03", "m", series, list(breakdowns))


def test_slowdown_fires_on_sustained_drop_and_links_the_breakdown_after_it():
    slow = [(DAY0 + timedelta(days=20 + d), v) for d, v in enumerate([15.0, 14.0, 13.0, 12.5])]
    seized = (77, datetime(2026, 10, 4, 4, 0, tzinfo=UTC), "Main shaft bearing seized")
    (found,) = detectors.machine_slowdowns([machine(steady(20) + slow, [seized])])
    facts = found["facts"]
    assert (facts["days"], facts["from"], facts["to"]) == (4, "2026-09-30", "2026-10-03")
    assert (facts["baseline_per_hour"], facts["low_per_hour"]) == (16.9, 12.5)
    assert facts["followed_by"]["reason"] == "Main shaft bearing seized"
    assert found["severity"] == "critical"
    assert narratives_cite_only_facts([found])


def test_slowdown_ignores_single_bad_days_and_steady_machines():
    dips = steady(24)
    dips[5] = (dips[5][0], 9.0)
    dips[15] = (dips[15][0], 8.0)
    assert detectors.machine_slowdowns([machine(dips), machine(steady(24))]) == []


def test_median_and_mad_are_not_pulled_by_a_breakdown_day():
    mid, zs = detectors.robust_z([17.0, 17.2, 16.8, 17.1, 0.5])
    assert mid == 17.0
    assert zs[-1] < -50 and all(abs(z) < 2 for z in zs[:-1])


def breakdowns(n, machine_id=1, code="LM-01", days_ago=1, reason="Belt slip", shift=(1, "A")):
    return [
        Breakdown(
            next(ids),
            machine_id,
            code,
            reason,
            *shift,
            NOW - timedelta(days=days_ago, hours=k),
            2.0,
        )
        for k in range(n)
    ]


def test_breakdown_cluster_on_one_machine_in_a_week():
    (found,) = detectors.breakdown_clusters(breakdowns(5) + breakdowns(6, days_ago=12), NOW)
    assert (found["entity_type"], found["entity_id"], found["facts"]["count"]) == ("machines", 1, 5)
    assert found["facts"]["downtime_hours"] == 10.0
    assert narratives_cite_only_facts([found])
    assert detectors.breakdown_clusters(breakdowns(3), NOW) == []


def test_same_reason_across_machines_is_a_cluster():
    events = breakdowns(2, 1, "LM-01", reason="Weft feeder fault") + breakdowns(
        2, 2, "LM-02", reason="weft feeder fault "
    )
    (found,) = detectors.breakdown_clusters(events, NOW)
    assert found["facts"]["what"] == "reason"
    assert found["facts"]["machines"] == ["LM-01", "LM-02"]


SHIFTS = [
    Shift(id=1, code="A", start_time=time(6), end_time=time(14)),
    Shift(id=2, code="B", start_time=time(14), end_time=time(22)),
    Shift(id=3, code="C", start_time=time(22), end_time=time(6)),
]


def spells(hh: int, mm: int, minutes: float, n: int = 10) -> list[IdleSpell]:
    local = datetime(2026, 10, 1, hh, mm, tzinfo=IST)
    return [
        IdleSpell(next(ids), f"LM-0{k % 6 + 1}", local + timedelta(days=k), minutes)
        for k in range(n)
    ]


def test_one_slow_handover_stands_out():
    found = detectors.shift_change_idle(
        spells(6, 5, 50) + spells(14, 3, 5) + spells(22, 2, 6) + spells(10, 0, 90), SHIFTS, 30
    )
    (only,) = found
    facts = only["facts"]
    assert (only["entity_id"], facts["from_shift"], facts["to_shift"], facts["at"]) == (
        1,
        "C",
        "A",
        "06:00",
    )
    assert (facts["spells"], facts["median_min"], facts["others_median_min"]) == (10, 50, 6)
    assert narratives_cite_only_facts(found)


def test_even_handovers_are_silent():
    assert (
        detectors.shift_change_idle(
            spells(6, 5, 6) + spells(14, 3, 5) + spells(22, 2, 6), SHIFTS, 30
        )
        == []
    )


# --- yarn yield and impossible data


def job(order_id, order, issued, expected=100.0, machine=(1, "LM-01")) -> YieldJob:
    return YieldJob(
        next(ids), "WO", order_id, order, *machine, 580.0, issued, expected, issued * 28500
    )


# SO-1: 216 kg issued for 200 kg of fabric -> 16 kg (8%) at Rs 285/kg = Rs 4560
def test_yield_gap_fires_for_the_order_that_ate_extra_yarn():
    found = detectors.yield_gaps([job(1, "SO-1", 108), job(1, "SO-1", 108), job(2, "SO-2", 100.3)])
    by_entity = {(f["entity_type"], f["entity_id"]): f["facts"] for f in found}
    order = by_entity["orders", 1]
    assert (order["gap_kg"], order["gap_pct"], order["value_rupees"]) == (16.0, 8.0, 4560)
    assert {"type": "orders", "id": 1, "code": "SO-1"} in order["records"]
    assert ("orders", 2) not in by_entity
    # the loom ran 3 jobs: 316.3 kg for 300 kg is 5.4%, so the machine view flags it too
    assert by_entity["machines", 1]["gap_pct"] == 5.4
    assert narratives_cite_only_facts(found)


def test_yield_within_tolerance_is_silent():
    assert (
        detectors.yield_gaps([job(1, "SO-1", 102), job(2, "SO-2", 101), job(3, "SO-3", 100)]) == []
    )


def at(hh, mm=0) -> datetime:
    return datetime(2026, 10, 1, hh, mm, tzinfo=UTC)


def test_output_inside_a_breakdown_window_is_impossible():
    down = Downtime(5, "LM-05", 900, "breakdown", "Take-up roller jam", at(10), at(13))
    logs = [OutputLog(k, 5, t, 6.0, "m") for k, t in ((1, at(11, 50)), (2, at(13)), (3, at(9, 59)))]
    logs.append(OutputLog(4, 6, at(11), 6.0, "m"))  # other machine
    (found,) = detectors.logs_in_downtime([down], logs)
    assert (found["entity_type"], found["entity_id"]) == ("production_logs", 1)
    assert found["facts"]["minutes_into_stop"] == 110
    assert narratives_cite_only_facts([found])


def test_rolls_cut_beyond_logged_output_are_impossible():
    def cut(total, logged):
        return CutRoll(next(ids), "R-000009", 4, "WO-000004", "LM-02", at(10), 60.0, total, logged)

    (found,) = detectors.rolls_too_long([cut(121.5, 120.0), cut(120.9, 120.0)])
    assert found["facts"]["cut_total_m"] == 121.5
    assert narratives_cite_only_facts([found])


def test_receipt_far_from_supplier_usual_is_flagged():
    lots = [Lot(next(ids), "YB", 1, "SLY", kg) for kg in (1000, 1000, 1500, 1000, 500, 15000)]
    (found,) = detectors.odd_receipts(lots)
    assert (found["facts"]["kg"], found["facts"]["usual_kg"], found["facts"]["ratio"]) == (
        15000,
        1000,
        15,
    )
    assert narratives_cite_only_facts([found])
    assert detectors.odd_receipts(lots[:5]) == []


# --- end to end on the database: real loaders, real upsert


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


def test_detectors_find_a_late_counter_log_once(db, floor):
    def event(status, ago, reason=None):
        db.add(
            MachineEvent(
                machine_id=floor.loom1.id,
                at=NOW - ago,
                status=status,
                reason=reason,
                source="machine",
            )
        )

    event(MachineStatus.breakdown, timedelta(hours=3), "Take-up roller jam")
    event(MachineStatus.running, timedelta(hours=1))
    db.add(
        ProductionLog(
            work_order_id=floor.shirt_weave.id,
            machine_id=floor.loom1.id,
            shift_id=floor.shifts[0].id,
            qty=6,
            unit="m",
            at=NOW - timedelta(hours=2),
        )
    )
    db.commit()

    assert service.run_detectors(db, NOW)["created"] == 1
    assert service.run_detectors(db, NOW) == {
        "created": 0,
        "updated": 0,
        "unchanged": 1,
        "skipped": 0,
    }
    insight = db.scalar(select(Insight))
    assert (insight.kind, insight.entity_type) == ("impossible_data", "production_logs")
    assert "60 min into a breakdown" in insight.narrative
