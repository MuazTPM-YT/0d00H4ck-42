from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errors import Conflict
from app.modules.auth.models import Role
from app.modules.workforce import service
from app.modules.workforce.models import Attendance, AttendanceSource, AttendanceStatus
from app.modules.workforce.schemas import AttendanceIn, CarryIn, CrewIn
from tests.floor import build_floor

DAY = date(2026, 10, 9)


@pytest.fixture
def floor(db, buyer, dyed_fabric):
    return build_floor(db, buyer, dyed_fabric)


def crew(floor, worker, machine, shift=0):
    return CrewIn(
        date=DAY, shift_id=floor.shifts[shift].id, worker_id=worker.id, machine_id=machine.id
    )


def attendance_rows(db, floor, worker):
    return db.scalars(select(Attendance).where(Attendance.worker_id == worker.id)).all()


@pytest.mark.parametrize(
    ("utc", "shift_code", "day"),
    [
        (datetime(2026, 10, 9, 1, 0, tzinfo=UTC), "TA", date(2026, 10, 9)),  # 06:30 IST
        (datetime(2026, 10, 9, 17, 0, tzinfo=UTC), "TC", date(2026, 10, 9)),  # 22:30 IST
        (datetime(2026, 10, 9, 20, 0, tzinfo=UTC), "TC", date(2026, 10, 9)),  # 01:30 IST next day
    ],
)
def test_current_shift_handles_night_shift_over_midnight(db, floor, utc, shift_code, day):
    on, shift = service.current_shift(db, utc)
    assert (shift.code, on) == (shift_code, day)


def test_crew_assignment_writes_attendance_once(db, floor):
    t0 = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
    service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id, t0)
    first = service.assign_crew(
        db, crew(floor, floor.weaver, floor.loom2), floor.supervisor.id, t0 + timedelta(hours=2)
    )
    rows = attendance_rows(db, floor, floor.weaver)
    assert [(r.status, r.source) for r in rows] == [
        (AttendanceStatus.present, AttendanceSource.crew)
    ]
    # moving closed the first assignment; the worker is on loom 2 now
    assert service.crew_on_machine(db, floor.loom1.id, t0 + timedelta(hours=3)) is None
    assert service.crew_on_machine(db, floor.loom2.id, t0 + timedelta(hours=3)) == floor.weaver.id
    assert first.to_at is None


def test_same_machine_twice_is_409(db, floor):
    service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id)
    with pytest.raises(Conflict):
        service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id)


def test_manual_attendance_upserts_and_crew_overrides_absent(db, floor):
    body = AttendanceIn(
        date=DAY,
        shift_id=floor.shifts[0].id,
        worker_id=floor.helper.id,
        status=AttendanceStatus.absent,
        reason="Called in sick",
    )
    service.set_attendance(db, body, floor.supervisor.id)
    service.set_attendance(db, body.model_copy(update={"status": "half_day"}), floor.supervisor.id)
    assert [r.status for r in attendance_rows(db, floor, floor.helper)] == ["half_day"]

    service.set_attendance(db, body, floor.supervisor.id)
    service.assign_crew(db, crew(floor, floor.helper, floor.loom1), floor.supervisor.id)
    assert [r.status for r in attendance_rows(db, floor, floor.helper)] == ["present"]


def test_future_date_rejected_and_roles_enforced(client_as, floor):
    body = {
        "date": str(date.today() + timedelta(days=2)),
        "shift_id": floor.shifts[0].id,
        "worker_id": floor.weaver.id,
        "machine_id": floor.loom1.id,
    }
    res = client_as(Role.supervisor).post("/api/workforce/crew", json=body)
    assert res.status_code == 422 and res.json()["error"]["field"] == "date"
    accounts = client_as(Role.accounts)
    assert accounts.post("/api/workforce/crew", json={**body, "date": str(DAY)}).status_code == 403
    assert accounts.get("/api/workforce/attendance").status_code == 200
    assert client_as(Role.qc).get("/api/workforce/attendance").status_code == 403


T0 = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)  # 06:30 IST, shift TA on DAY
TA_END = datetime(2026, 10, 9, 8, 30, tzinfo=UTC)  # 14:00 IST


def test_crew_lookup_ignores_an_assignment_left_open_from_an_earlier_shift(db, floor):
    service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id, T0)
    assert service.crew_on_machine(db, floor.loom1.id, T0 + timedelta(hours=1)) == floor.weaver.id
    # nobody closed it, but shift TB is a different shift; weeks later even more so
    assert service.crew_on_machine(db, floor.loom1.id, T0 + timedelta(hours=9)) is None
    assert service.crew_on_machine(db, floor.loom1.id, T0 + timedelta(days=20)) is None


def test_assignment_for_a_past_shift_covers_that_shift(db, floor):
    row = service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id)
    assert (row.from_at, row.to_at) == (datetime(2026, 10, 9, 0, 30, tzinfo=UTC), TA_END)
    assert service.crew_on_machine(db, floor.loom1.id, T0 + timedelta(hours=3)) == floor.weaver.id


def test_next_shift_closes_assignments_still_open_from_earlier_shifts(db, floor):
    first = service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id, T0)
    service.assign_crew(
        db, crew(floor, floor.helper, floor.loom2, shift=1), floor.supervisor.id, TA_END
    )
    assert first.to_at == TA_END


def test_carry_crew_brings_the_last_shift_onto_the_same_machines(client_as, db, floor):
    sup = floor.supervisor.id
    service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), sup, T0)
    service.assign_crew(db, crew(floor, floor.helper, floor.loom2), sup, T0)
    absent = AttendanceIn(
        date=DAY,
        shift_id=floor.shifts[1].id,
        worker_id=floor.helper.id,
        status=AttendanceStatus.absent,
        reason="Leave",
    )
    service.set_attendance(db, absent, sup)
    body = CarryIn(
        date=DAY, shift_id=floor.shifts[1].id, from_date=DAY, from_shift_id=floor.shifts[0].id
    )
    assert service.carry_crew(db, body, sup, TA_END) == 1
    rows = service.list_crew(db, DAY, floor.shifts[1].id)
    assert [(r["worker_id"], r["machine_id"]) for r in rows] == [(floor.weaver.id, floor.loom1.id)]
    old = service.list_crew(db, DAY, floor.shifts[0].id)
    assert {r["to_at"] for r in old} == {TA_END}
    assert service.carry_crew(db, body, sup, TA_END) == 0  # already there

    backwards = {**body.model_dump(mode="json"), "from_shift_id": floor.shifts[2].id}
    res = client_as(Role.supervisor).post("/api/workforce/crew/carry", json=backwards)
    assert res.status_code == 422 and res.json()["error"]["field"] == "from_shift_id"


def test_absent_refused_while_on_a_machine_that_shift(db, floor):
    service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id, T0)
    body = AttendanceIn(
        date=DAY,
        shift_id=floor.shifts[0].id,
        worker_id=floor.weaver.id,
        status=AttendanceStatus.absent,
        reason="Not here",
    )
    with pytest.raises(Conflict):
        service.set_attendance(db, body, floor.supervisor.id)


def test_attendance_locked_once_wages_are_final(db, floor):
    from app.modules.finance.models import WageRun, WageRunStatus

    db.add(WageRun(period_start=DAY, period_end=DAY, status=WageRunStatus.final))
    db.flush()
    body = AttendanceIn(
        date=DAY,
        shift_id=floor.shifts[0].id,
        worker_id=floor.weaver.id,
        status=AttendanceStatus.present,
        reason="Came late",
    )
    with pytest.raises(Conflict) as e:
        service.set_attendance(db, body, floor.supervisor.id)
    assert e.value.code == "period_locked"
    with pytest.raises(Conflict):
        service.assign_crew(db, crew(floor, floor.weaver, floor.loom1), floor.supervisor.id, T0)
