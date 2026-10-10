import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.modules.analytics import detectors, explainer, service
from app.modules.analytics.models import Insight, InsightStatus, Severity
from app.modules.auth.models import Role


def finding(kind="machine_slowdown", entity_id=7, key="2026-10-01", drop=22.5, **kw) -> dict:
    return {
        "kind": kind,
        "severity": Severity.warn,
        "entity_type": "machines",
        "entity_id": entity_id,
        "title": "LM-03 slowed down",
        "facts": {"key": key, "machine": "LM-03", "drop_pct": drop, "records": []},
        **kw,
    }


@pytest.fixture(autouse=True)
def simple_text(monkeypatch):
    for kind in service.KIND_ROLES:
        monkeypatch.setitem(explainer.TEMPLATES, kind, lambda f: f"Drop {f.get('drop_pct')}%.")


def count(db) -> int:
    return db.scalar(select(func.count()).select_from(Insight))


def test_same_finding_twice_is_one_insight_updated_in_place(db):
    assert service.upsert_insight(db, finding()) == "created"
    assert service.upsert_insight(db, finding()) == "unchanged"
    assert service.upsert_insight(db, finding(drop=30.0)) == "updated"
    db.commit()
    assert count(db) == 1
    insight = db.scalar(select(Insight))
    assert insight.facts["drop_pct"] == 30.0
    assert insight.narrative == "Drop 30.0%."


def test_new_episode_key_is_a_new_insight_but_resolved_one_stays_quiet(db):
    service.upsert_insight(db, finding())
    db.commit()
    insight = db.scalar(select(Insight))
    insight.status = InsightStatus.resolved
    db.commit()
    assert service.upsert_insight(db, finding(drop=40.0)) == "skipped"
    assert service.upsert_insight(db, finding(key="2026-10-09")) == "created"
    assert count(db) == 2


def test_run_detectors_is_idempotent_and_audits_new_findings(db, monkeypatch):
    monkeypatch.setattr(detectors, "find_all", lambda db, now: [finding(), finding(entity_id=8)])
    assert service.run_detectors(db) == {"created": 2, "updated": 0, "unchanged": 0, "skipped": 0}
    assert service.run_detectors(db) == {"created": 0, "updated": 0, "unchanged": 2, "skipped": 0}
    assert count(db) == 2
    detected = select(func.count()).where(AuditLog.action == "detected")
    assert db.scalar(detected) == 2


@pytest.fixture
def two_insights(db):
    service.upsert_insight(db, finding())
    service.upsert_insight(db, finding(kind="supplier_defects", entity_id=3))
    db.commit()
    return {i.kind: i for i in db.scalars(select(Insight))}


def kinds(c) -> set[str]:
    return {i["kind"] for i in c.get("/api/analytics/insights").json()["items"]}


def test_each_role_sees_only_its_kinds(client_as, two_insights):
    store = client_as(Role.store)
    assert kinds(store) == {"supplier_defects"}
    hidden = two_insights["machine_slowdown"].id
    assert store.get(f"/api/analytics/insights/{hidden}").status_code == 404
    assert kinds(client_as(Role.supervisor)) == {"machine_slowdown"}
    assert kinds(client_as(Role.owner)) == {"supplier_defects", "machine_slowdown"}


def test_acknowledge_then_resolve_with_note_follows_transition_map(client_as, db, two_insights):
    c = client_as(Role.supervisor)
    path = f"/api/analytics/insights/{two_insights['machine_slowdown'].id}"
    assert c.post(f"{path}/acknowledge", json={"note": "   "}).status_code == 422
    assert c.post(f"{path}/acknowledge", json={"note": "Fitter checking"}).json()["status"] == (
        "acknowledged"
    )
    res = c.post(f"{path}/acknowledge", json={"note": "again"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "illegal_transition"
    assert c.post(f"{path}/resolve", json={"note": "Bearing replaced"}).status_code == 200
    reasons = db.scalars(select(AuditLog.reason).where(AuditLog.entity_type == "insights"))
    assert {"Fitter checking", "Bearing replaced"} <= set(reasons)


def test_only_supervisor_or_owner_runs_detectors(client_as, monkeypatch):
    monkeypatch.setattr(detectors, "find_all", lambda db, now: [])
    assert client_as(Role.qc).post("/api/analytics/run").status_code == 403
    assert client_as(Role.supervisor).post("/api/analytics/run").json()["created"] == 0


def test_counts_follow_role_and_status_and_search_finds_title(client_as, db, two_insights):
    two_insights["machine_slowdown"].severity = Severity.critical
    db.commit()
    owner = client_as(Role.owner)
    counts = owner.get("/api/analytics/insights/counts?status=open").json()
    assert counts["by_status"] == {"open": 2, "acknowledged": 0, "resolved": 0}
    assert counts["by_severity"] == {"info": 0, "warn": 1, "critical": 1}
    assert [k["kind"] for k in counts["by_kind"]] == ["machine_slowdown", "supplier_defects"]
    hits = owner.get("/api/analytics/insights?q=lm-03").json()
    assert hits["total"] == 2
    assert owner.get("/api/analytics/insights?q=nothing-like-this").json()["total"] == 0
    # client_as re-points the one test client, so the store view comes last
    store = client_as(Role.store).get("/api/analytics/insights/counts").json()
    assert [k["kind"] for k in store["by_kind"]] == ["supplier_defects"]
