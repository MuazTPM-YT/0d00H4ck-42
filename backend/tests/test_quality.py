from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import Conflict, Unprocessable
from app.modules.auth.models import Role
from app.modules.inventory.models import MoveReason, StockMove
from app.modules.masters.models import Location, LocationKind
from app.modules.production import service as production
from app.modules.production.models import WorkOrder
from app.modules.production.schemas import OutputIn, RollIn, RollProcessIn
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
    f.issue(f.shirt_weave, f.batches[0], 100)  # store issues yarn before the loom starts
    production.start_work_order(db, f.shirt_weave.id, f.supervisor.id)
    return f


# shirting is weaving only, so a fresh cut lands straight in the QC queue
def roll_waiting(db, floor, length=50) -> Roll:
    out = OutputIn(machine_id=floor.loom1.id, qty=Decimal(length))
    production.log_output(db, out, floor.supervisor.id)  # loom weaves it before it is cut
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


# --- 4-point score, repeat scans, ledger guard, checks list, trace


def test_hole_scores_four_and_score_is_per_100_square_metres():
    defects = [{"type": "hole", "count": 2}, {"type": "stain", "count": 3, "points": 2}]
    points = service.defect_points(defects)
    assert points == 2 * 4 + 3 * 2
    # 100 m x 1.5 m = 150 m2 -> 14 points x 100 / 150
    assert service.points_per_100m2(points, Decimal(100), Decimal(150)) == Decimal("9.3")
    assert service.points_per_100m2(points, Decimal(100), None) is None


def test_each_defect_type_once(db, floor, client_as):
    roll = roll_waiting(db, floor)
    twice = [{"type": "stain", "count": 1}, {"type": "stain", "count": 2}]
    res = client_as(Role.qc).post(
        f"/api/quality/rolls/{roll.id}/checks", json={"decision": "rework", "defects": twice}
    )
    assert res.status_code == 422 and res.json()["error"]["field"] == "defects"


def test_same_scan_twice_saves_once(db, floor, client_as):
    roll = roll_waiting(db, floor)
    qc = client_as(Role.qc)
    body = {"decision": "pass", "shade_band": "A", "idempotency_key": "tablet-7-0001"}
    first = qc.post(f"/api/quality/rolls/{roll.id}/checks", json=body)
    second = qc.post(f"/api/quality/rolls/{roll.id}/checks", json=body)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert db.scalar(select(func.count()).where(QcCheck.roll_id == roll.id)) == 1


def test_roll_off_its_ledger_location_is_refused(db, floor, make_user):
    roll = roll_waiting(db, floor)
    roll.location_id = floor.loc[LocationKind.finished].id  # row says shelf, ledger says floor
    db.commit()
    with pytest.raises(Conflict) as e:
        decide(db, roll, make_user(Role.qc), decision="pass", shade_band="A")
    assert e.value.code == "stock_mismatch"


def test_rework_stage_must_be_on_the_route(db, floor, make_user):
    roll = roll_waiting(db, floor)
    with pytest.raises(Unprocessable):
        decide(
            db,
            roll,
            make_user(Role.qc),
            decision="rework",
            defects=[{"type": "colour_mismatch", "count": 1}],
            rework_stage="dyeing",
        )


def test_checks_list_and_trace_follow_the_rework_loop(db, floor, client_as):
    roll = roll_waiting(db, floor, 40)
    qc = client_as(Role.qc)
    url = f"/api/quality/rolls/{roll.id}/checks"
    defects = [{"type": "broken_pick", "count": 2, "points": 3}, {"type": "hole", "count": 1}]
    res = qc.post(url, json={"decision": "rework", "defects": defects})
    assert res.status_code == 201, res.text
    job = db.get(WorkOrder, res.json()["rework_work_order_id"])
    production.queue_work_order(db, job.id, floor.loom2.id, floor.supervisor.id)
    production.start_work_order(db, job.id, floor.supervisor.id)
    production.process_roll(db, roll.id, RollProcessIn(work_order_id=job.id), None)
    body = {"decision": "pass", "shade_band": "A", "gsm": "115", "width_cm": "147"}
    assert qc.post(url, json=body).status_code == 201

    checks = qc.get(f"/api/quality/checks?roll_id={roll.id}").json()
    assert checks["total"] == 2 and checks["items"][0]["decision"] == "pass"
    rework = checks["items"][1]
    assert rework["points"] == 2 * 3 + 4  # hole forced to 4 points
    assert rework["defects"][1] == {"type": "hole", "count": 1, "points": 4}

    trace = client_as(Role.dispatch).get(f"/api/quality/rolls/{roll.id}/trace").json()
    assert trace["roll"]["status"] == "passed"
    assert [c["decision"] for c in trace["checks"]] == ["rework", "pass"]
    assert [y["supplier_lot"] for y in trace["yarn"]] == ["LOT-1"]
    assert [j["code"] for j in trace["rework_jobs"]] == [job.code]
    assert [e["kind"] for e in trace["events"]] == ["woven", "qc_rework", "rework", "qc_pass"]
    assert trace["rework_stages"] == ["weaving"]


def test_find_roll_by_scanned_code(db, floor, client_as):
    roll = roll_waiting(db, floor)
    res = client_as(Role.qc).get(f"/api/quality/rolls?code={roll.code.lower()}")
    assert [r["id"] for r in res.json()["items"]] == [roll.id]


# rework only helps an order still being made; a cancelled or closed order gets a reject
def test_rework_refused_when_order_not_confirmed(db, floor, make_user):
    from app.modules.orders.models import Order, OrderStatus

    roll = roll_waiting(db, floor)
    db.get(Order, roll.order_id).status = OrderStatus.cancelled
    db.commit()
    with pytest.raises(Conflict) as e:
        decide(
            db, roll, make_user(Role.qc), decision="rework", defects=[{"type": "hole", "count": 1}]
        )
    assert "reject" in e.value.message.lower()
    db.refresh(roll)
    assert roll.status == RollStatus.awaiting_qc


# two checks already: third look must settle it
def test_third_check_cannot_rework_again(db, floor, client_as):
    roll = roll_waiting(db, floor)
    qc = client_as(Role.qc)
    url = f"/api/quality/rolls/{roll.id}/checks"
    body = {"decision": "rework", "defects": [{"type": "stain", "count": 1}]}
    for _ in range(2):
        assert qc.post(url, json=body).status_code == 201
        roll.status = RollStatus.awaiting_qc  # rework job done (covered in test_production)
        db.commit()
    res = qc.post(url, json=body)
    assert res.status_code == 409 and "Third check" in res.json()["error"]["message"]
    assert qc.post(url, json={**body, "decision": "reject"}).status_code == 201


def test_roll_detail_carries_order_status(db, floor, client_as):
    roll = roll_waiting(db, floor)
    body = client_as(Role.qc).get(f"/api/quality/rolls/{roll.id}").json()
    assert body["order_status"] == "confirmed"
