from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.enums import Source, Stage, Unit
from app.core.errors import Conflict, Unprocessable
from app.core.units import qty, yarn_kg_for_fabric
from app.modules.auth.models import Role
from app.modules.inventory.models import ItemKind, MoveReason, StockMove
from app.modules.masters.models import LocationKind
from app.modules.orders.models import Order, OrderStatus
from app.modules.production import service
from app.modules.production.models import MachineEvent, MachineStatus, WorkOrder, WorkOrderStatus
from app.modules.production.schemas import MachineEventIn, OutputIn, RollIn, RollProcessIn
from app.modules.production.service import create_work_orders
from app.modules.quality.models import Roll, RollBatch, RollStatus
from app.modules.workforce.schemas import IST, CrewIn
from app.modules.workforce.service import assign_crew, current_shift
from tests.floor import build_floor


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


def report(db, floor, machine, status, reason=None, **kw):
    body = MachineEventIn(machine_id=machine.id, status=status, reason=reason, **kw)
    return service.report_machine_event(db, body, floor.supervisor.id)


# first stage of a route needs yarn issued to its order before it may start
def run_on(db, floor, wo, machine, issue=True):
    if issue and wo.roll_id is None and wo.seq == 1:
        floor.issue(wo, floor.batches[0], 50)
    service.queue_work_order(db, wo.id, machine.id, floor.supervisor.id)
    if wo.status == WorkOrderStatus.queued:
        service.start_work_order(db, wo.id, floor.supervisor.id)
    return wo


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
    # 5% process allowance so rejected rolls still leave the order's metres
    assert all(w.planned_qty == Decimal(525) and w.code.startswith("WO-") for w in wos)
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


def test_paused_job_holds_its_machine_for_start_and_move(db, floor):
    shirt = run_on(db, floor, floor.shirt_weave, floor.loom1)
    report(db, floor, floor.loom1, MachineStatus.idle)  # supervisor stops it, job paused
    floor.issue(floor.dyed_weave, floor.batches[0], 50)
    service.queue_work_order(db, floor.dyed_weave.id, floor.loom1.id, floor.supervisor.id)
    assert floor.dyed_weave.status == WorkOrderStatus.queued  # no auto-start over a paused job
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, floor.dyed_weave.id, floor.supervisor.id)
    assert e.value.code == "machine_busy"

    service.move_work_order(db, floor.dyed_weave.id, floor.loom2.id, "free", floor.supervisor.id)
    service.start_work_order(db, floor.dyed_weave.id, floor.supervisor.id)
    report(db, floor, floor.loom2, MachineStatus.breakdown, "Belt slip")
    with pytest.raises(Conflict) as e:
        service.move_work_order(db, floor.dyed_weave.id, floor.loom1.id, "x", floor.supervisor.id)
    assert e.value.code == "machine_busy" and shirt.status == WorkOrderStatus.paused


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
    now = datetime.now(UTC)
    day, shift = current_shift(db, now)
    floor_crew = CrewIn(
        date=day, shift_id=shift.id, worker_id=floor.weaver.id, machine_id=floor.loom1.id
    )
    assign_crew(db, floor_crew, floor.supervisor.id, now - timedelta(minutes=1))
    row = log(db, floor, floor.loom1, "12.5", source=Source.machine)
    assert row["work_order_id"] == wo.id and row["unit"] == "m"
    assert row["worker_id"] == floor.weaver.id and row["shift_id"] == shift.id


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
        "planned": Decimal(630),  # 600 m + 5% allowance
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


def cut(db, floor, wo, length):
    return service.cut_roll(db, RollIn(work_order_id=wo.id, length_m=Decimal(length)), None)


# weave then cut, the way a loom does it
def weave(db, floor, wo, machine, *lengths):
    log(db, floor, machine, sum(Decimal(n) for n in lengths), work_order_id=wo.id)
    return [cut(db, floor, wo, n) for n in lengths]


def test_split_kg_is_proportional_and_exact():
    parts = service.split_kg(Decimal("10.000"), {1: Decimal(1), 2: Decimal(1), 3: Decimal(1)})
    assert sum(parts.values()) == Decimal("10.000")
    assert sorted(parts.values()) == [Decimal("3.333"), Decimal("3.333"), Decimal("3.334")]


def test_roll_lineage_sums_to_formula_kg_split_by_issued_share(db, floor):
    wo = floor.shirt_weave
    service.queue_work_order(db, wo.id, floor.loom1.id, floor.supervisor.id)
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, wo.id, floor.supervisor.id)
    assert e.value.code == "no_yarn_issued"
    assert e.value.message == f"The store issues yarn to {wo.code} first"

    b1, b2 = floor.batches
    floor.issue(wo, b1, 90)
    floor.issue(wo, b2, 30)
    service.start_work_order(db, wo.id, floor.supervisor.id)
    (roll,) = weave(db, floor, wo, floor.loom1, 60)
    rows = db.scalars(select(RollBatch).where(RollBatch.roll_id == roll["id"])).all()
    kg = yarn_kg_for_fabric(Decimal(60), Decimal(147), Decimal(115), Decimal(5))
    by_batch = {r.yarn_batch_id: r.kg for r in rows}
    assert sum(by_batch.values()) == kg
    assert by_batch[b1.id] == qty(kg * 3 / 4)  # 90 of 120 kg issued came from batch 1
    assert roll["code"].startswith("R-") and roll["loom_machine_id"] == floor.loom1.id


def test_lineage_reads_yarn_issued_to_any_route_job_of_the_order(db, floor):
    floor.issue(floor.dyed_dye, floor.batches[1], 40)  # not the loom job
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1, issue=False)
    (roll,) = weave(db, floor, weave_wo, floor.loom1, 60)
    rows = db.scalars(select(RollBatch).where(RollBatch.roll_id == roll["id"])).all()
    assert [r.yarn_batch_id for r in rows] == [floor.batches[1].id]


def test_output_needs_yarn_issued_to_the_order(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    # the store takes it all back: nothing of the order is on the floor any more
    db.add(
        StockMove(
            at=datetime.now(UTC),
            item_kind=ItemKind.yarn,
            yarn_batch_id=floor.batches[0].id,
            qty=Decimal(50),
            unit=Unit.kg,
            from_location_id=floor.loc[LocationKind.wip].id,
            to_location_id=floor.loc[LocationKind.store].id,
            reason=MoveReason.return_,
            ref_type="work_order",
            ref_id=wo.id,
        )
    )
    db.commit()
    with pytest.raises(Conflict) as e:
        log(db, floor, floor.loom1, 5)
    assert e.value.code == "no_yarn_issued"


def test_cut_cannot_roll_more_than_was_woven(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    with pytest.raises(Conflict) as e:
        cut(db, floor, wo, 10)
    assert e.value.code == "more_than_woven"
    log(db, floor, floor.loom1, 100)
    cut(db, floor, wo, 60)
    with pytest.raises(Conflict) as e:
        cut(db, floor, wo, 50)
    assert e.value.field == "length_m"


def test_finish_cuts_the_tail_into_a_roll(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    weave(db, floor, wo, floor.loom1, 60)
    log(db, floor, floor.loom1, "40.5")
    service.finish_work_order(db, wo.id, floor.supervisor.id)
    lengths = db.scalars(select(Roll.length_m).where(Roll.work_order_id == wo.id)).all()
    assert sorted(lengths) == [Decimal("40.5"), Decimal(60)]


def test_last_stage_moves_roll_to_awaiting_qc(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    (roll,) = weave(db, floor, wo, floor.loom1, 55)
    assert roll["status"] == RollStatus.awaiting_qc  # shirting: weaving only


def test_dyed_roll_waits_for_dyeing_then_qc(db, floor):
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    (roll,) = weave(db, floor, weave_wo, floor.loom1, 60)
    assert roll["status"] == RollStatus.in_process

    dye = run_on(db, floor, floor.dyed_dye, floor.jigger)
    body = RollProcessIn(work_order_id=dye.id)
    done = service.process_roll(db, roll["id"], body, None)
    assert done["status"] == RollStatus.awaiting_qc
    assert service.order_progress(db, floor.dyed_order.id)["dyeing"]["produced"] == 60
    with pytest.raises(Conflict):
        service.process_roll(db, roll["id"], body, None)


def test_later_stage_starts_after_earlier_started_and_a_roll_waits(db, floor):
    dye = floor.dyed_dye
    service.queue_work_order(db, dye.id, floor.jigger.id, floor.supervisor.id)
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, dye.id, floor.supervisor.id)
    assert e.value.code == "stage_order"
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, dye.id, floor.supervisor.id)
    assert e.value.code == "no_rolls_waiting"
    weave(db, floor, weave_wo, floor.loom1, 60)
    service.start_work_order(db, dye.id, floor.supervisor.id)
    assert dye.status == WorkOrderStatus.running


def test_dyeing_finishes_only_after_weaving_and_every_roll_dyed(db, floor):
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    first, second = weave(db, floor, weave_wo, floor.loom1, 60, 30)
    dye = run_on(db, floor, floor.dyed_dye, floor.jigger)
    service.process_roll(db, first["id"], RollProcessIn(work_order_id=dye.id), None)
    with pytest.raises(Conflict) as e:
        service.finish_work_order(db, dye.id, floor.supervisor.id)
    assert e.value.code == "stage_order"  # weaving still running

    service.finish_work_order(db, weave_wo.id, floor.supervisor.id)
    assert dye.status == WorkOrderStatus.running  # one roll still waits
    with pytest.raises(Conflict) as e:
        service.finish_work_order(db, dye.id, floor.supervisor.id)
    assert e.value.code == "rolls_waiting"
    service.process_roll(db, second["id"], RollProcessIn(work_order_id=dye.id), None)
    assert dye.status == WorkOrderStatus.done  # nothing left to dye: finished by itself
    assert service.machine_status(db, floor.jigger.id) == MachineStatus.idle


def test_dye_all_waiting_rolls_in_one_call(client_as, db, floor):
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    weave(db, floor, weave_wo, floor.loom1, 60, 55)
    dye = run_on(db, floor, floor.dyed_dye, floor.jigger)
    sup = client_as(Role.supervisor)
    url = f"/api/production/work-orders/{dye.id}/process-waiting"
    body = {"source": "machine", "idempotency_key": "jig-batch-0001"}
    res = sup.post(url, json=body)
    assert res.status_code == 200, res.text
    assert res.json() == {"work_order_id": dye.id, "processed": 2}
    assert sup.post(url, json=body).json() == {"work_order_id": dye.id, "processed": 2}
    statuses = db.scalars(select(Roll.status).where(Roll.order_id == floor.dyed_order.id)).all()
    assert statuses == [RollStatus.awaiting_qc] * 2
    assert service.order_progress(db, floor.dyed_order.id)["dyeing"]["produced"] == 115


def test_paused_job_can_finish_while_its_machine_is_down(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    log(db, floor, floor.loom1, 30)
    report(db, floor, floor.loom1, MachineStatus.breakdown, "Motor burnt")
    service.finish_work_order(db, wo.id, floor.supervisor.id)
    assert wo.status == WorkOrderStatus.done
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.breakdown
    statuses = db.scalars(
        select(MachineEvent.status)
        .where(MachineEvent.machine_id == floor.loom1.id)
        .order_by(MachineEvent.id)
    ).all()
    assert statuses == [MachineStatus.running, MachineStatus.breakdown]
    assert db.scalar(select(Roll.length_m).where(Roll.work_order_id == wo.id)) == 30


def test_output_reaching_planned_finishes_and_next_job_starts(db, floor):
    shirt = run_on(db, floor, floor.shirt_weave, floor.loom1)
    floor.issue(floor.dyed_weave, floor.batches[0], 50)
    service.queue_work_order(db, floor.dyed_weave.id, floor.loom1.id, floor.supervisor.id)
    assert floor.dyed_weave.status == WorkOrderStatus.queued
    log(db, floor, floor.loom1, 630)  # 600 m order + 5%
    assert shirt.status == WorkOrderStatus.done
    assert db.scalar(select(Roll.length_m).where(Roll.work_order_id == shirt.id)) == 630
    assert floor.dyed_weave.status == WorkOrderStatus.running  # pulled off the queue
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.running


def test_queue_on_an_idle_machine_starts_the_job(db, floor):
    report(db, floor, floor.loom1, MachineStatus.idle)
    floor.issue(floor.shirt_weave, floor.batches[0], 50)
    service.queue_work_order(db, floor.shirt_weave.id, floor.loom1.id, floor.supervisor.id)
    assert floor.shirt_weave.status == WorkOrderStatus.running


def test_a_first_woven_roll_lets_queued_dyeing_start(db, floor):
    report(db, floor, floor.jigger, MachineStatus.idle)
    weave_wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    service.queue_work_order(db, floor.dyed_dye.id, floor.jigger.id, floor.supervisor.id)
    assert floor.dyed_dye.status == WorkOrderStatus.queued  # no roll to dye yet
    weave(db, floor, weave_wo, floor.loom1, 60)
    assert floor.dyed_dye.status == WorkOrderStatus.running


def test_machine_coming_on_starts_its_queue(db, floor):
    floor.issue(floor.shirt_weave, floor.batches[0], 50)
    service.queue_work_order(db, floor.shirt_weave.id, floor.loom1.id, floor.supervisor.id)
    assert floor.shirt_weave.status == WorkOrderStatus.queued  # machine is off
    report(db, floor, floor.loom1, MachineStatus.idle)
    assert floor.shirt_weave.status == WorkOrderStatus.running


def reworked_roll(db, floor, length=40):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    (cut_one,) = weave(db, floor, wo, floor.loom1, length)
    roll = db.get(Roll, cut_one["id"])
    roll.status = RollStatus.rework  # quality module's decision
    db.commit()
    return roll


def test_rework_work_order_returns_roll_to_qc(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)
    (cut_one,) = weave(db, floor, wo, floor.loom1, 40)
    roll = db.get(Roll, cut_one["id"])
    with pytest.raises(Conflict):
        service.create_rework_work_order(db, roll.id, Stage.weaving, None)  # not in rework yet
    roll.status = RollStatus.rework  # quality module's decision
    db.commit()
    with pytest.raises(Unprocessable):
        service.create_rework_work_order(db, roll.id, Stage.dyeing, None)  # not on route

    rework = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    assert (rework.roll_id, rework.planned_qty, rework.status) == (
        roll.id,
        roll.length_m,
        "waiting",
    )
    assert service.create_rework_work_order(db, roll.id, Stage.weaving, None).id == rework.id

    run_on(db, floor, rework, floor.loom2)
    result = service.process_roll(db, roll.id, RollProcessIn(work_order_id=rework.id), None)
    assert result["status"] == RollStatus.awaiting_qc
    assert rework.status == WorkOrderStatus.done  # one roll, one job: done when processed


def test_second_rework_of_a_roll_gets_a_new_job(db, floor):
    roll = reworked_roll(db, floor)
    first = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    run_on(db, floor, first, floor.loom2)
    service.process_roll(db, roll.id, RollProcessIn(work_order_id=first.id), None)
    roll.status = RollStatus.rework  # failed QC again
    db.commit()
    second = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    assert second.id != first.id and second.status == WorkOrderStatus.waiting


def test_rework_job_finishes_only_by_processing_its_roll(db, floor):
    roll = reworked_roll(db, floor)
    rework = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    run_on(db, floor, rework, floor.loom2)
    with pytest.raises(Conflict) as e:
        service.finish_work_order(db, rework.id, floor.supervisor.id)
    assert e.value.message == f"Process {roll.code} first"


def test_rework_jumps_the_queue_preempts_and_hands_the_loom_back(db, floor):
    roll = reworked_roll(db, floor)
    shirt = floor.shirt_weave
    floor.issue(floor.dyed_weave, floor.batches[0], 50)
    service.queue_work_order(db, floor.dyed_weave.id, floor.loom1.id, floor.supervisor.id)
    rework = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    service.queue_work_order(db, rework.id, floor.loom1.id, floor.supervisor.id)
    assert (rework.queue_position, floor.dyed_weave.queue_position) == (1, 2)

    events_before = db.scalar(select(func.count()).select_from(MachineEvent))
    service.start_work_order(db, rework.id, floor.supervisor.id)
    assert (shirt.status, rework.status) == (WorkOrderStatus.paused, WorkOrderStatus.running)
    assert db.scalar(select(func.count()).select_from(MachineEvent)) == events_before
    reason = db.scalar(
        select(AuditLog.reason)
        .where(AuditLog.entity_type == "work_orders", AuditLog.entity_id == shirt.id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert reason == f"rework {roll.code}"

    service.process_roll(db, roll.id, RollProcessIn(work_order_id=rework.id), None)
    assert (shirt.status, rework.status) == (WorkOrderStatus.running, WorkOrderStatus.done)
    assert floor.dyed_weave.status == WorkOrderStatus.queued
    assert service.machine_status(db, floor.loom1.id) == MachineStatus.running


def test_repair_resumes_the_job_the_breakdown_hit(db, floor):
    roll = reworked_roll(db, floor)
    rework = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    service.queue_work_order(db, rework.id, floor.loom1.id, floor.supervisor.id)
    service.start_work_order(db, rework.id, floor.supervisor.id)
    report(db, floor, floor.loom1, MachineStatus.breakdown, "Belt slip")
    report(db, floor, floor.loom1, MachineStatus.running)
    assert rework.status == WorkOrderStatus.running
    assert floor.shirt_weave.status == WorkOrderStatus.paused


def test_finish_consumes_yarn_left_on_the_floor(db, floor):
    wo = run_on(db, floor, floor.shirt_weave, floor.loom1)  # 50 kg issued
    service.finish_work_order(db, wo.id, None)
    consumed = db.scalars(
        select(StockMove).where(StockMove.ref_id == wo.id, StockMove.reason == "consume")
    ).all()
    assert [m.qty for m in consumed] == [Decimal(50)]


def test_cancelled_order_jobs_leave_the_floor(client_as, db, floor):
    for wo in (floor.shirt_weave, floor.dyed_weave):
        service.queue_work_order(db, wo.id, floor.loom1.id, floor.supervisor.id)
    assert service.release_order_jobs(db, floor.dyed_order.id, floor.supervisor.id) == 1
    db.commit()
    assert (floor.dyed_weave.status, floor.dyed_weave.machine_id) == ("waiting", None)

    floor.issue(floor.shirt_weave, floor.batches[0], 50)
    floor.shirt_order.status = OrderStatus.cancelled
    db.commit()
    with pytest.raises(Conflict) as e:
        service.start_work_order(db, floor.shirt_weave.id, floor.supervisor.id)
    assert e.value.code == "order_not_open"
    with pytest.raises(Conflict):
        service.reorder_queue(db, floor.loom1.id, [floor.shirt_weave.id], floor.supervisor.id)
    tiles = {
        t["code"]: t for t in client_as(Role.owner).get("/api/production/board").json()["machines"]
    }
    assert tiles["LM-T1"]["queued"] == 0


def test_release_refuses_an_order_with_a_job_on_a_machine(db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    with pytest.raises(Conflict) as e:
        service.release_order_jobs(db, floor.shirt_order.id, floor.supervisor.id)
    assert e.value.code == "job_on_machine"


def test_status_durations_one_pass():
    t = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    events = [
        (t - timedelta(hours=1), MachineStatus.running),  # in effect at window start
        (t + timedelta(hours=2), MachineStatus.breakdown),
        (t + timedelta(hours=3), MachineStatus.idle),
    ]
    got = service.status_durations(events, t, t + timedelta(hours=4))
    assert (got["running"], got["breakdown"], got["idle"]) == (7200, 3600, 3600)
    assert service.status_durations([], t, t + timedelta(hours=1))["off"] == 3600


def test_board_shows_job_progress_and_todays_output(client_as, db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    log(db, floor, floor.loom1, 20)
    log(db, floor, floor.loom1, "4.5")
    res = client_as(Role.owner).get("/api/production/board")
    assert res.status_code == 200, res.text
    tiles = {t["code"]: t for t in res.json()["machines"]}
    lm1 = tiles["LM-T1"]
    assert lm1["status"] == "running" and lm1["today_output"] == "24.500"
    assert lm1["source"] == "manual"
    assert lm1["job"]["code"] == floor.shirt_weave.code and lm1["job"]["produced"] == "24.500"
    assert tiles["LM-T2"]["status"] == "off" and tiles["LM-T2"]["job"] is None


def test_rework_output_is_not_new_production(client_as, db, floor):
    roll = reworked_roll(db, floor)
    rework = service.create_rework_work_order(db, roll.id, Stage.weaving, None)
    db.commit()
    run_on(db, floor, rework, floor.loom2)
    service.process_roll(db, roll.id, RollProcessIn(work_order_id=rework.id), None)
    tiles = {
        t["code"]: t for t in client_as(Role.owner).get("/api/production/board").json()["machines"]
    }
    assert tiles["LM-T2"]["today_output"] == "0.000"
    today = datetime.now(UTC).astimezone(IST).date()
    assert service.timeline(db, floor.loom2.id, today)["total_output"] == 0


def test_timeline_lists_todays_events_and_output(client_as, db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    log(db, floor, floor.loom1, 10)
    report(db, floor, floor.loom1, MachineStatus.breakdown, "Belt slip")
    today = datetime.now(UTC).astimezone(IST).date()
    res = client_as(Role.qc).get(f"/api/production/machines/{floor.loom1.id}/timeline?date={today}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [e["status"] for e in body["events"]] == ["running", "breakdown"]
    assert body["total_output"] == "10.000"


def test_open_work_orders_carry_order_code_and_progress(client_as, db, floor):
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    log(db, floor, floor.loom1, 12)
    res = client_as(Role.supervisor).get("/api/production/work-orders/open")
    assert res.status_code == 200, res.text
    rows = {r["code"]: r for r in res.json()}
    assert rows[floor.shirt_weave.code]["order_code"] == "SO-T1"
    assert rows[floor.shirt_weave.code]["produced"] == "12.000"
    assert rows[floor.dyed_dye.code]["status"] == "waiting"


def test_store_issuing_yarn_starts_the_queued_first_stage_job(db, floor):
    from app.modules.inventory import service as inventory
    from app.modules.inventory.schemas import IssueIn

    batch = floor.batches[0]
    db.add(
        StockMove(
            at=datetime.now(UTC),
            item_kind=ItemKind.yarn,
            yarn_batch_id=batch.id,
            qty=Decimal(500),
            unit=Unit.kg,
            from_location_id=floor.loc[LocationKind.supplier].id,
            to_location_id=floor.loc[LocationKind.store].id,
            reason=MoveReason.receipt,
        )
    )
    report(db, floor, floor.loom1, MachineStatus.idle)
    service.queue_work_order(db, floor.shirt_weave.id, floor.loom1.id, floor.supervisor.id)
    assert floor.shirt_weave.status == WorkOrderStatus.queued  # no yarn on the floor yet
    data = IssueIn(
        work_order_id=floor.shirt_weave.id, yarn_batch_id=batch.id, kg=50, reason="Extra for test"
    )
    inventory.issue(db, floor.supervisor, data)
    assert floor.shirt_weave.status == WorkOrderStatus.running


# issued yarn is the hand-off: the job goes to the least busy working loom by itself;
# a stage with no working machine waits for the supervisor
def test_issued_yarn_puts_the_waiting_job_on_the_least_busy_loom(db, floor):
    report(db, floor, floor.loom1, MachineStatus.idle)
    report(db, floor, floor.loom2, MachineStatus.idle)
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    assert floor.dyed_weave.status == WorkOrderStatus.waiting  # no yarn yet
    floor.issue(floor.dyed_weave, floor.batches[1], 50)
    service.advance(db, floor.supervisor.id)
    db.commit()
    assert floor.dyed_weave.machine_id == floor.loom2.id
    assert floor.dyed_weave.status == WorkOrderStatus.running
    assert floor.dyed_dye.status == WorkOrderStatus.waiting  # the jigger is off


# weaving done: the dye job goes onto the free dye range by itself and starts on the rolls
def test_dyeing_is_planned_once_weaving_is_done(db, floor):
    report(db, floor, floor.jigger, MachineStatus.idle)
    wo = run_on(db, floor, floor.dyed_weave, floor.loom1)
    weave(db, floor, wo, floor.loom1, 60)
    assert floor.dyed_dye.status == WorkOrderStatus.waiting  # weaving still running
    log(db, floor, floor.loom1, wo.planned_qty - 60, work_order_id=wo.id)  # reaches plan
    assert wo.status == WorkOrderStatus.done
    assert floor.dyed_dye.machine_id == floor.jigger.id
    assert floor.dyed_dye.status == WorkOrderStatus.running


# a dye job whose order has no woven roll yet must not block the next job in the queue
def test_a_dye_job_with_no_roll_yet_does_not_hold_up_the_next(db, floor, buyer, dyed_fabric):
    report(db, floor, floor.jigger, MachineStatus.idle)
    run_on(db, floor, floor.dyed_weave, floor.loom1)
    service.queue_work_order(db, floor.dyed_dye.id, floor.jigger.id, floor.supervisor.id)
    assert floor.dyed_dye.status == WorkOrderStatus.queued  # nothing to dye yet
    other = Order(
        code="SO-T3",
        buyer_id=buyer.id,
        fabric_type_id=dyed_fabric.id,
        colour="Raw White",
        qty_m=Decimal(100),
        rate_paise_per_m=20000,
        deadline=floor.dyed_order.deadline,
        status=OrderStatus.confirmed,
        confirmed_at=datetime.now(UTC),
    )
    db.add(other)
    db.flush()
    weave_wo, dye_wo = create_work_orders(db, other.id, None)
    db.commit()
    run_on(db, floor, weave_wo, floor.loom2)
    service.queue_work_order(db, dye_wo.id, floor.jigger.id, floor.supervisor.id)
    assert dye_wo.queue_position == 2
    weave(db, floor, weave_wo, floor.loom2, 60)
    assert dye_wo.status == WorkOrderStatus.running
    assert floor.dyed_dye.status == WorkOrderStatus.queued


# cancel never strands a loom: refused while a job runs, queued jobs go back to waiting
def test_cancel_refused_while_a_job_runs(db, floor):
    from app.modules.orders import service as orders

    sup = floor.supervisor
    run_on(db, floor, floor.dyed_weave, floor.loom1)
    service.queue_work_order(db, floor.dyed_dye.id, floor.jigger.id, sup.id)
    with pytest.raises(Conflict) as stopped:
        orders.cancel_order(db, sup, floor.dyed_order.id, "Buyer pulled out")
    assert stopped.value.code == "job_running"

    service.finish_work_order(db, floor.dyed_weave.id, sup.id)
    orders.cancel_order(db, sup, floor.dyed_order.id, "Buyer pulled out")
    db.refresh(floor.dyed_dye)
    assert floor.dyed_dye.status == WorkOrderStatus.waiting
    assert floor.dyed_dye.machine_id is None and floor.dyed_dye.queue_position is None


# jobs of an order that is no longer open cannot start, log output or cut rolls
def test_jobs_of_a_cancelled_order_cannot_run(db, floor):
    from app.modules.orders.models import OrderStatus

    sup = floor.supervisor
    run_on(db, floor, floor.shirt_weave, floor.loom1)
    report(db, floor, floor.loom1, MachineStatus.idle)  # job pauses with the machine
    floor.shirt_order.status = OrderStatus.cancelled
    db.commit()

    calls = [
        lambda: service.start_work_order(db, floor.shirt_weave.id, sup.id),
        lambda: service.log_output(
            db, OutputIn(machine_id=floor.loom1.id, qty=Decimal(10)), sup.id
        ),
        lambda: service.cut_roll(
            db, RollIn(work_order_id=floor.shirt_weave.id, length_m=Decimal(50)), None
        ),
    ]
    for call in calls:
        with pytest.raises(Conflict) as refused:
            call()
        assert refused.value.code == "order_not_open"
        db.rollback()
