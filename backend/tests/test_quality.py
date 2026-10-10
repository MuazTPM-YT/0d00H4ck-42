from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.modules.auth.models import Role
from app.modules.inventory.models import MoveReason, StockMove
from app.modules.masters.models import Location, LocationKind
from app.modules.production import service as production
from app.modules.production.models import WorkOrder
from app.modules.production.schemas import RollIn, RollProcessIn
from app.modules.quality import service
from app.modules.quality.models import QcCheck, Roll, RollStatus
from tests.floor import build_floor
from tests.mill import Mill

PASS = {"decision": "pass", "shade_band": "A", "gsm": "101.5", "width_cm": "149"}


@pytest.fixture
def mill(db):
    return Mill(db)


@pytest.fixture
def waiting(db, mill):
    roll = mill.roll(mill.work_order(mill.order()), 100, RollStatus.awaiting_qc)
    db.commit()
    return roll


def inspect(client, roll, **body):
    return client.post(f"/api/quality/rolls/{roll.id}/inspect", json=body)


def moves(db, roll):
    return db.execute(
        select(StockMove.reason, StockMove.ref_type).where(StockMove.roll_id == roll.id)
    ).all()


# --- 4-point system (pure)


def test_hole_scores_four_and_score_is_per_100_square_metres():
    defects = [{"type": "hole", "count": 2}, {"type": "stain", "count": 3, "points": 2}]
    points = service.defect_points(defects)
    assert points == 2 * 4 + 3 * 2
    # 100 m x 1.5 m = 150 m2 -> 14 points x 100 / 150
    assert service.points_per_100m2(points, Decimal(100), Decimal(150)) == Decimal("9.3")
    assert service.points_per_100m2(points, Decimal(100), None) is None


# --- inspect through the API


def test_pass_moves_roll_to_finished_shelf_with_shade(client_as, db, mill, waiting):
    res = inspect(client_as(Role.qc), waiting, **PASS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "passed" and body["check"]["attempt_no"] == 1
    db.refresh(waiting)
    assert waiting.shade_band == "A" and waiting.passed_at is not None
    assert waiting.location_id == mill.loc["FG-01"].id
    assert (MoveReason.qc_pass, "qc_check") in moves(db, waiting)
    assert db.scalar(
        select(AuditLog).where(AuditLog.entity_type == "rolls", AuditLog.action == "passed")
    )


def test_pass_needs_shade_gsm_and_width(client_as, waiting):
    qc = client_as(Role.qc)
    for missing in ("shade_band", "gsm", "width_cm"):
        res = inspect(qc, waiting, **{k: v for k, v in PASS.items() if k != missing})
        assert res.status_code == 422 and res.json()["error"]["field"] == missing


def test_reject_needs_a_defect_and_goes_to_reject_store(client_as, db, mill, waiting):
    qc = client_as(Role.qc)
    res = inspect(qc, waiting, decision="reject")
    assert res.status_code == 422 and res.json()["error"]["field"] == "defects"
    res = inspect(qc, waiting, decision="reject", defects=[{"type": "hole", "count": 3}])
    assert res.status_code == 200, res.text
    check = res.json()["check"]
    assert check["defects"] == [{"type": "hole", "count": 3, "points": 4}]
    assert check["points"] == 12
    db.refresh(waiting)
    assert waiting.status == RollStatus.rejected and waiting.location_id == mill.loc["REJ"].id
    assert (MoveReason.qc_reject, "qc_check") in moves(db, waiting)


def test_each_defect_type_once(client_as, waiting):
    twice = [{"type": "stain", "count": 1}, {"type": "stain", "count": 2}]
    res = inspect(client_as(Role.qc), waiting, decision="rework", defects=twice)
    assert res.status_code == 422 and res.json()["error"]["field"] == "defects"


def test_only_waiting_rolls_are_inspected(client_as, mill, waiting):
    qc = client_as(Role.qc)
    assert inspect(qc, waiting, **PASS).status_code == 200
    again = inspect(qc, waiting, **PASS)
    assert again.status_code == 409 and again.json()["error"]["code"] == "illegal_transition"
    fresh = mill.roll(mill.work_order(mill.order()), 50, RollStatus.in_process)
    assert inspect(qc, fresh, **PASS).status_code == 409


def test_only_qc_inspects(client_as, waiting):
    assert inspect(client_as(Role.store), waiting, **PASS).status_code == 403
    assert client_as(Role.dispatch).get(f"/api/quality/rolls/{waiting.id}").status_code == 200


def test_same_scan_twice_saves_once(client_as, db, waiting):
    qc = client_as(Role.qc)
    first = inspect(qc, waiting, **PASS, idempotency_key="tablet-7-0001")
    second = inspect(qc, waiting, **PASS, idempotency_key="tablet-7-0001")
    assert second.status_code == 200 and second.json() == first.json()
    assert db.scalar(select(func.count()).where(QcCheck.roll_id == waiting.id)) == 1


def test_roll_off_its_ledger_location_is_refused(client_as, db, mill, waiting):
    waiting.location_id = mill.loc["FG-01"].id  # row says shelf, ledger says floor
    db.commit()
    res = inspect(client_as(Role.qc), waiting, **PASS)
    assert res.status_code == 409 and res.json()["error"]["code"] == "stock_mismatch"


# --- full loop: loom cuts, QC sends to rework, loom redoes it, QC passes; trace shows it all


def test_rework_loop_and_trace(client_as, db, buyer, dyed_fabric):
    floor = build_floor(db, buyer, dyed_fabric)
    db.add_all(
        [
            Location(code="FG", name="Shelf", kind=LocationKind.finished),
            Location(code="REJ", name="Rejects", kind=LocationKind.rejected),
        ]
    )
    db.commit()
    production.queue_work_order(db, floor.shirt_weave.id, floor.loom1.id, floor.supervisor.id)
    wo = production.start_work_order(db, floor.shirt_weave.id, floor.supervisor.id)
    floor.issue(wo, floor.batches[0], 50)
    roll = db.get(
        Roll, production.cut_roll(db, RollIn(work_order_id=wo.id, length_m=40), None)["id"]
    )

    qc = client_as(Role.qc)
    queue = qc.get("/api/quality/queue").json()
    assert [r["code"] for r in queue["items"]] == [roll.code]
    assert queue["items"][0]["attempt_no"] == 1 and queue["items"][0]["loom_code"] == "LM-T1"

    res = inspect(qc, roll, decision="rework", defects=[{"type": "broken_pick", "count": 2}])
    assert res.status_code == 200, res.text
    job = db.get(WorkOrder, res.json()["rework_work_order_id"])
    assert (job.roll_id, job.stage, job.status) == (roll.id, "weaving", "waiting")
    assert qc.get("/api/quality/queue").json()["total"] == 0

    production.queue_work_order(db, job.id, floor.loom2.id, floor.supervisor.id)
    production.start_work_order(db, job.id, floor.supervisor.id)
    production.process_roll(db, roll.id, RollProcessIn(work_order_id=job.id), None)
    res = inspect(qc, roll, **PASS)
    assert res.status_code == 200 and res.json()["check"]["attempt_no"] == 2

    trace = qc.get(f"/api/quality/rolls/{roll.id}").json()
    assert trace["roll"]["status"] == "passed" and trace["roll"]["location_code"] == "FG"
    assert [c["decision"] for c in trace["checks"]] == ["rework", "pass"]
    assert [y["supplier_lot"] for y in trace["yarn"]] == ["LOT-1"]
    assert trace["weaver"] is None and trace["shift"]["code"] in ("TA", "TB", "TC")
    assert [j["code"] for j in trace["rework_jobs"]] == [job.code]
    assert [e["kind"] for e in trace["events"]] == ["woven", "rework"]
    assert trace["rework_stages"] == ["weaving"]

    summary = qc.get("/api/quality/summary?days=7").json()
    assert (summary["checked"], summary["passed"], summary["rework"]) == (2, 1, 1)
    assert summary["first_pass_yield_pct"] == "0.0"
    assert summary["by_defect"] == [{"type": "broken_pick", "rolls": 1, "count": 2, "points": 2}]
    assert summary["by_loom"][0]["code"] == "LM-T1" and summary["by_loom"][0]["checked"] == 2
    checks = qc.get(f"/api/quality/checks?roll_id={roll.id}").json()
    assert checks["total"] == 2 and checks["items"][0]["decision"] == "pass"


def test_find_roll_by_scanned_code(client_as, waiting):
    res = client_as(Role.qc).get(f"/api/quality/rolls?code={waiting.code.lower()}")
    assert [r["id"] for r in res.json()["items"]] == [waiting.id]
