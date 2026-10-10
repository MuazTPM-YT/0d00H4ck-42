from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.modules.auth.models import Role
from app.modules.inventory.models import MoveReason, StockMove
from app.modules.masters.models import Location, LocationKind
from app.modules.production import service as production
from app.modules.production.models import WorkOrder
from app.modules.production.schemas import RollIn
from app.modules.quality import service
from app.modules.quality.models import QcCheck, Roll, RollEvent, RollStatus
from app.modules.quality.schemas import QcCheckIn
from tests.floor import build_floor


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    f = build_floor(db, buyer, dyed_fabric)
    for kind in (LocationKind.finished, LocationKind.rejected):
        f.loc[kind] = Location(code=kind.upper()[:8], name=kind, kind=kind)
        db.add(f.loc[kind])
    db.commit()
    production.queue_work_order(db, f.shirt_weave.id, f.loom1.id, f.supervisor.id)
    production.start_work_order(db, f.shirt_weave.id, f.supervisor.id)
    f.issue(f.shirt_weave, f.batches[0], 100)
    return f


# shirting is weaving only, so a fresh cut lands straight in the QC queue
def roll_waiting(db, floor, length=50) -> Roll:
    body = RollIn(work_order_id=floor.shirt_weave.id, length_m=Decimal(length))
    return db.get(Roll, production.cut_roll(db, body, None)["id"])


def decide(db, roll, user, **body):
    return service.decide(db, roll.id, QcCheckIn(**body), user.id)


def moves(db, roll):
    return db.scalars(
        select(StockMove.reason).where(StockMove.roll_id == roll.id).order_by(StockMove.id)
    ).all()


def test_pass_sends_roll_to_finished_goods(db, floor, make_user):
    qc = make_user(Role.qc)
    roll = roll_waiting(db, floor)
    out = decide(db, roll, qc, decision="pass", shade_band="B", gsm="116.5")
    db.refresh(roll)
    assert (roll.status, roll.shade_band, roll.location_id) == (
        RollStatus.passed,
        "B",
        floor.loc[LocationKind.finished].id,
    )
    assert roll.passed_at is not None
    assert out["check"].attempt_no == 1 and out["check"].inspector_id == qc.id
    assert moves(db, roll) == [MoveReason.produce, MoveReason.qc_pass]
    kinds = db.scalars(select(RollEvent.kind).where(RollEvent.roll_id == roll.id)).all()
    assert "qc_pass" in kinds


def test_reject_moves_roll_to_rejected(db, floor, make_user):
    qc = make_user(Role.qc)
    roll = roll_waiting(db, floor)
    decide(db, roll, qc, decision="reject", defects=[{"type": "hole", "count": 3}])
    db.refresh(roll)
    assert roll.status == RollStatus.rejected
    assert roll.location_id == floor.loc[LocationKind.rejected].id
    assert moves(db, roll)[-1] == MoveReason.qc_reject


def test_rework_opens_job_and_second_attempt_counts(db, floor, make_user):
    qc = make_user(Role.qc)
    roll = roll_waiting(db, floor)
    out = decide(db, roll, qc, decision="rework", defects=[{"type": "uneven_weave", "count": 2}])
    db.refresh(roll)
    assert roll.status == RollStatus.rework
    wo = db.get(WorkOrder, out["rework_work_order_id"])
    assert (wo.roll_id, wo.stage) == (roll.id, "weaving")
    assert moves(db, roll) == [MoveReason.produce]  # fabric stays in WIP

    roll.status = RollStatus.awaiting_qc  # rework job done (covered in test_production)
    db.commit()
    again = decide(db, roll, qc, decision="pass", shade_band="A")
    assert again["check"].attempt_no == 2
    attempts = db.scalars(select(QcCheck.attempt_no).where(QcCheck.roll_id == roll.id)).all()
    assert sorted(attempts) == [1, 2]


def test_decided_roll_cannot_be_decided_again(db, floor, make_user):
    qc = make_user(Role.qc)
    roll = roll_waiting(db, floor)
    decide(db, roll, qc, decision="pass", shade_band="A")
    with pytest.raises(Conflict):
        decide(db, roll, qc, decision="reject", defects=[{"type": "other", "count": 1}])


def test_api_rules(db, floor, client_as):
    roll = roll_waiting(db, floor)
    url = f"/api/quality/rolls/{roll.id}/checks"
    sup = client_as(Role.supervisor)
    assert sup.post(url, json={"decision": "pass", "shade_band": "A"}).status_code == 403

    qc = client_as(Role.qc)
    r = qc.post(url, json={"decision": "pass"})
    assert r.status_code == 422 and r.json()["error"]["field"] == "shade_band"
    r = qc.post(url, json={"decision": "reject"})
    assert r.status_code == 422 and r.json()["error"]["field"] == "defects"

    assert qc.post(url, json={"decision": "pass", "shade_band": "A"}).status_code == 201
    r = qc.post(url, json={"decision": "pass", "shade_band": "A"})
    assert r.status_code == 409


def test_queue_and_detail_carry_names(db, floor, client_as):
    first, second = roll_waiting(db, floor, 40), roll_waiting(db, floor, 45)
    qc = client_as(Role.qc)
    body = qc.get("/api/quality/queue").json()
    assert body["total"] == 2
    row = body["items"][0]
    assert row["id"] in (first.id, second.id)
    assert (row["order_code"], row["loom_code"], row["buyer_name"]) == (
        "SO-T1",
        "LM-T1",
        "Test Buyer",
    )
    assert row["fabric_name"] == "Test Shirting" and row["shift_name"]

    detail = qc.get(f"/api/quality/rolls/{first.id}").json()
    assert detail["code"] == first.code and detail["checks"] == []


def test_summary_counts_decisions_and_defects(db, floor, make_user, client_as):
    qc = make_user(Role.qc)
    a, b, c = (roll_waiting(db, floor) for _ in range(3))
    decide(db, a, qc, decision="pass", shade_band="A")
    decide(db, b, qc, decision="rework", defects=[{"type": "hole", "count": 2}])
    decide(
        db,
        c,
        qc,
        decision="reject",
        defects=[{"type": "hole", "count": 1}, {"type": "colour_mismatch", "count": 1}],
    )
    roll_waiting(db, floor)

    s = client_as(Role.owner).get("/api/quality/summary?days=30").json()
    assert s["waiting"] == 1
    assert s["first_attempt"] == {"passed": 1, "rework": 1, "rejected": 1}
    assert s["all_attempts"] == s["first_attempt"]
    assert s["pass_rate_pct"] == pytest.approx(33.3)
    assert s["defects_by_type"] == {"hole": 3, "colour_mismatch": 1}
    assert s["by_machine"] == [{"key": "LM-T1", "checks": 3, "defects": 4}]
    assert s["by_order"] == [{"key": "SO-T1", "checks": 3, "defects": 4}]
