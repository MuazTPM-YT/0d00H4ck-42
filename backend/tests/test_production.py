from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.enums import Source
from app.core.errors import Conflict
from app.modules.auth.models import Role
from app.modules.orders.models import Order
from app.modules.production import service
from app.modules.production.models import MachineStatus, WorkOrder, WorkOrderStatus
from app.modules.production.schemas import MachineEventIn, OutputIn
from app.modules.production.service import create_work_orders
from app.modules.workforce.schemas import CrewIn
from app.modules.workforce.service import assign_crew
from tests.floor import build_floor


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


def report(db, floor, machine, status, reason=None, **kw):
    body = MachineEventIn(machine_id=machine.id, status=status, reason=reason, **kw)
    return service.report_machine_event(db, body, floor.supervisor.id)


def run_on(db, floor, wo, machine):
    service.queue_work_order(db, wo.id, machine.id, floor.supervisor.id)
    return service.start_work_order(db, wo.id, floor.supervisor.id)


def test_one_waiting_work_order_per_route_stage(db, buyer, dyed_fabric):
    order = Order(
        code="SO-T2",
        buyer_id=buyer.id,
        fabric_type_id=dyed_fabric.id,
        colour="Maroon",
        qty_m=Decimal(500),
        rate_paise_per_m=24000,
        deadline="2026-12-01",
    )
    db.add(order)
    db.flush()

    wos = create_work_orders(db, order.id, None)
    db.flush()  # sessions run with autoflush off
    assert [(w.stage, w.seq, w.unit, w.status) for w in wos] == [
        ("weaving", 1, "m", WorkOrderStatus.waiting),
        ("dyeing", 2, "m", WorkOrderStatus.waiting),
    ]
    assert all(w.planned_qty == Decimal(500) and w.code.startswith("WO-") for w in wos)
    assert db.scalar(select(AuditLog).where(AuditLog.entity_type == "work_orders")) is not None

    again = create_work_orders(db, order.id, None)
    assert [w.id for w in again] == [w.id for w in wos]
    assert len(db.scalars(select(WorkOrder).where(WorkOrder.order_id == order.id)).all()) == 2


def test_machine_never_reported_is_off_and_repeat_status_is_409(db, floor):
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.off
    report(db, floor, floor.loom1, MachineStatus.idle)
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.idle
    with pytest.raises(Conflict) as e:
        report(db, floor, floor.loom1, MachineStatus.idle)
    assert e.value.code == "illegal_transition"


def test_work_order_transition_map_is_enforced(db, floor):
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, floor.shirt_weave.id, floor.supervisor.id)  # waiting
    assert e.value.code == "illegal_transition"
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    service.finish_work_order(db, floor.shirt_weave.id, floor.supervisor.id)
    with pytest.raises(Conflict):
        service.start_work_order(db, floor.shirt_weave.id, floor.supervisor.id)  # done


def test_queue_needs_matching_machine_type(db, floor):
    with pytest.raises(Conflict) as e:
        service.queue_work_order(db, floor.shirt_weave.id, floor.jigger.id, floor.supervisor.id)
    assert e.value.field == "machine_id"


def test_start_writes_running_event_and_finish_writes_idle(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    assert wo.status == WorkOrderStatus.running and wo.started_at is not None
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.running
    service.finish_work_order(db, wo.id, floor.supervisor.id)
    assert wo.status == WorkOrderStatus.done and wo.finished_at >= wo.started_at
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.idle


def test_breakdown_pauses_running_work_order_and_running_resumes_it(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    event = report(db, floor, floor.loom1, MachineStatus.breakdown, "Warp beam snapped")
    assert wo.status == WorkOrderStatus.paused
    assert event["work_order_id"] == wo.id  # breakdown names the job it hit
    report(db, floor, floor.loom1, MachineStatus.running)
    assert wo.status == WorkOrderStatus.running


def test_breakdown_needs_reason(db, floor):
    with pytest.raises(ValueError):
        MachineEventIn(machine_id=floor.loom1.id, status=MachineStatus.breakdown)


def test_broken_machine_takes_no_new_work_and_paused_work_moves(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    report(db, floor, floor.loom1, MachineStatus.breakdown, "Motor burnt")
    with pytest.raises(Conflict) as e:
        service.queue_work_order(db, floor.dyed_weave.id, floor.loom1.id, floor.supervisor.id)
    assert e.value.code == "machine_down"

    service.move_work_order(db, wo.id, floor.loom2.id, "LM-T1 motor", floor.supervisor.id)
    assert wo.machine_id == floor.loom2.id and wo.status == WorkOrderStatus.paused
    service.start_work_order(db, wo.id, floor.supervisor.id)
    assert wo.status == WorkOrderStatus.running
    assert service.machine_status(db, floor.loom2.id) == MachineStatus.running


def test_one_running_work_order_per_machine(db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    service.queue_work_order(db, floor.dyed_weave.id, floor.loom1.id, floor.supervisor.id)
    with pytest.raises(Conflict):
        service.start_work_order(db, floor.dyed_weave.id, floor.supervisor.id)


def test_reorder_queue_sets_positions_and_rejects_stale_set(db, floor):
    a, b = floor.shirt_weave, floor.dyed_weave
    for wo in (a, b):
        service.queue_work_order(db, wo.id, floor.loom1.id, floor.supervisor.id)
    assert (a.queue_position, b.queue_position) == (1, 2)
    service.reorder_queue(db, floor.loom1.id, [b.id, a.id], floor.supervisor.id)
    assert (a.queue_position, b.queue_position) == (2, 1)
    with pytest.raises(Conflict) as e:
        service.reorder_queue(db, floor.loom1.id, [a.id], floor.supervisor.id)
    assert e.value.field == "work_order_ids"


def test_idempotent_machine_event(db, floor):
    key = "feed-lm1-000001"
    first = report(db, floor, floor.loom1, MachineStatus.idle, idempotency_key=key)
    again = report(db, floor, floor.loom1, MachineStatus.idle, idempotency_key=key)
    assert first == again


def test_only_supervisor_writes_floor_events(client_as, floor):
    body = {"machine_id": floor.loom1.id, "status": "idle"}
    assert (
        client_as(Role.store).post("/api/production/machine-events", json=body).status_code == 403
    )
    sup = client_as(Role.supervisor)
    res = sup.post("/api/production/machine-events", json=body)
    assert res.status_code == 201, res.text
    bad = {"machine_id": floor.loom1.id, "status": "breakdown", "reason": "   "}
    res = sup.post("/api/production/machine-events", json=bad)
    assert res.status_code == 422 and res.json()["error"]["field"] == "reason"


def log(db, floor, machine, qty, **kw):
    body = OutputIn(machine_id=machine.id, qty=Decimal(qty), **kw)
    return service.log_output(db, body, floor.supervisor.id)


def test_output_derives_work_order_shift_and_worker(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    floor_crew = CrewIn(
        date=datetime.now(UTC).date() - timedelta(days=1),  # any date; lookup is by time
        shift_id=floor.shifts[0].id,
        worker_id=floor.weaver.id,
        machine_id=floor.loom1.id,
    )
    assign_crew(db, floor_crew, floor.supervisor.id, datetime.now(UTC) - timedelta(minutes=1))
    row = log(db, floor, floor.loom1, "12.5", source=Source.machine)
    assert row["work_order_id"] == wo.id and row["unit"] == "m"
    assert row["worker_id"] == floor.weaver.id and row["shift_id"] is not None


def test_output_rejected_during_breakdown(db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    report(db, floor, floor.loom1, MachineStatus.breakdown, "Shuttle jam")
    with pytest.raises(Conflict) as e:
        log(db, floor, floor.loom1, 5)
    assert e.value.code == "machine_down"


def test_output_needs_a_started_job_on_that_machine(db, floor):
    with pytest.raises(Conflict):
        log(db, floor, floor.loom1, 5)
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    with pytest.raises(Conflict):
        log(db, floor, floor.loom2, 5, work_order_id=floor.shirt_weave.id)


def test_progress_is_logged_over_planned(db, floor):
    run_on(db, floor, floor.dyed_weave, floor.loom1)
    for q in ("100", "50.5"):
        log(db, floor, floor.loom1, q)
    progress = service.order_progress(db, floor.dyed_order.id)
    assert progress["weaving"] == {
        "planned": Decimal(600),
        "produced": Decimal("150.5"),
        "unit": "m",
    }
    assert progress["dyeing"]["produced"] == 0


def test_idempotent_output_posts_once(db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    first = log(db, floor, floor.loom1, 7, idempotency_key="lm1-count-0042")
    again = log(db, floor, floor.loom1, 7, idempotency_key="lm1-count-0042")
    assert first == again
    assert service.order_progress(db, floor.shirt_order.id)["weaving"]["produced"] == 7


def test_output_time_must_be_recent():
    with pytest.raises(ValueError, match="future"):
        OutputIn(machine_id=1, qty=1, at=datetime.now(UTC) + timedelta(hours=1))
    with pytest.raises(ValueError, match="24 hours"):
        OutputIn(machine_id=1, qty=1, at=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(ValueError):
        OutputIn(machine_id=1, qty=0)
