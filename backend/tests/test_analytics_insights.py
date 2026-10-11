import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.modules.analytics import detectors, explainer, service
from app.modules.analytics.models import Insight, InsightStatus, Severity
from app.modules.auth.models import Role, User


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
    first = {"created": 2, "updated": 0, "unchanged": 0, "skipped": 0, "resolved": 0}
    assert service.run_detectors(db) == first
    again = {"created": 0, "updated": 0, "unchanged": 2, "skipped": 0, "resolved": 0}
    assert service.run_detectors(db) == again
    assert count(db) == 2
    detected = select(func.count()).where(AuditLog.action == "detected")
    assert db.scalar(detected) == 2


# a finding the detectors stop producing closes itself; hand-made kinds and acknowledged ones stay
def test_run_closes_open_findings_it_no_longer_produces(db, monkeypatch):
    seeded = Insight(
        kind="machine_downtime",
        severity=Severity.warn,
        entity_type="machine",
        entity_id=1,
        title="seeded",
        facts={},
    )
    db.add(seeded)
    monkeypatch.setattr(
        detectors,
        "find_all",
        lambda db, now: [finding(), finding(entity_id=8), finding(entity_id=9)],
    )
    service.run_detectors(db)
    by_entity = {
        i.entity_id: i
        for i in db.scalars(select(Insight).where(Insight.kind != "machine_downtime"))
    }
    by_entity[9].status = InsightStatus.acknowledged
    db.commit()

    monkeypatch.setattr(detectors, "find_all", lambda db, now: [finding()])
    assert service.run_detectors(db)["resolved"] == 1
    assert by_entity[7].status == InsightStatus.open
    assert by_entity[8].status == InsightStatus.resolved
    assert by_entity[9].status == InsightStatus.acknowledged
    assert seeded.status == InsightStatus.open
    row = db.scalar(
        select(AuditLog).where(AuditLog.entity_id == by_entity[8].id, AuditLog.action == "resolved")
    )
    assert row.user_id is None and row.data == {"auto": True}


# closed by the run, not by a person: when the problem comes back it is raised again
def test_auto_closed_finding_comes_back_but_person_resolved_stays_quiet(db, monkeypatch):
    monkeypatch.setattr(detectors, "find_all", lambda db, now: [finding(), finding(entity_id=8)])
    service.run_detectors(db)
    monkeypatch.setattr(detectors, "find_all", lambda db, now: [finding()])
    service.run_detectors(db)
    assert service.upsert_insight(db, finding(entity_id=8)) == "created"
    db.commit()
    live = db.scalar(select(Insight).where(Insight.entity_id == 7))
    user = User(name="QC", email="qc@insights.test", role=Role.supervisor, password_hash="x")
    db.add(user)
    db.commit()
    service.set_insight_status(db, live.id, InsightStatus.resolved, "Fixed the beam", user)
    assert service.upsert_insight(db, finding()) == "skipped"


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
