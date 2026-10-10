from datetime import UTC, datetime, timedelta
from itertools import count

from app.modules.analytics import detectors, explainer
from app.modules.analytics.detectors import GateBatch, QcRoll

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
