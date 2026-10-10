from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import Page, paginate
from app.modules.finance import service as finance
from app.modules.masters.models import Machine, Shift, Worker
from app.modules.workforce.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    CrewAssignment,
)
from app.modules.workforce.schemas import IST, AttendanceIn, CarryIn, CrewIn


def list_attendance(
    db: Session, page: Page, on: date | None = None, shift_id: int | None = None
) -> dict:
    stmt = select(Attendance).order_by(
        Attendance.date.desc(), Attendance.shift_id, Attendance.worker_id
    )
    if on:
        stmt = stmt.where(Attendance.date == on)
    if shift_id:
        stmt = stmt.where(Attendance.shift_id == shift_id)
    return paginate(db, stmt, page)


# which shift is on at this moment; a night shift belongs to the date it started
def current_shift(db: Session, at: datetime) -> tuple[date, Shift]:
    local = at.astimezone(IST)
    now = local.time()
    for shift in db.scalars(select(Shift).order_by(Shift.start_time)):
        if shift.start_time < shift.end_time:
            if shift.start_time <= now < shift.end_time:
                return local.date(), shift
        elif now >= shift.start_time:
            return local.date(), shift
        elif now < shift.end_time:
            return local.date() - timedelta(days=1), shift
    raise NotFound("No shift covers this time. Check the shift master.")


# UTC start and end of one shift on one date
def shift_window(day: date, shift: Shift) -> tuple[datetime, datetime]:
    start = datetime.combine(day, shift.start_time, IST)
    end_day = day if shift.start_time < shift.end_time else day + timedelta(days=1)
    return start.astimezone(UTC), datetime.combine(end_day, shift.end_time, IST).astimezone(UTC)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), IST).astimezone(UTC)


# who was on this machine at that moment: only an assignment of the shift that covers it
def crew_on_machine(db: Session, machine_id: int, at: datetime) -> int | None:
    try:
        day, shift = current_shift(db, at)
    except NotFound:
        return None
    return db.scalar(
        select(CrewAssignment.worker_id)
        .where(
            CrewAssignment.machine_id == machine_id,
            CrewAssignment.date == day,
            CrewAssignment.shift_id == shift.id,
            CrewAssignment.from_at <= at,
            or_(CrewAssignment.to_at.is_(None), CrewAssignment.to_at > at),
        )
        .order_by(CrewAssignment.from_at.desc())
        .limit(1)
    )


def list_crew(db: Session, on: date, shift_id: int) -> list[dict]:
    rows = db.execute(
        select(CrewAssignment, Worker.code, Worker.name, Machine.code)
        .join(Worker, Worker.id == CrewAssignment.worker_id)
        .join(Machine, Machine.id == CrewAssignment.machine_id)
        .where(CrewAssignment.date == on, CrewAssignment.shift_id == shift_id)
        .order_by(Machine.code, CrewAssignment.from_at)
    ).all()
    return [
        {
            "id": a.id,
            "date": a.date,
            "shift_id": a.shift_id,
            "worker_id": a.worker_id,
            "worker_code": worker_code,
            "worker_name": worker_name,
            "machine_id": a.machine_id,
            "machine_code": machine_code,
            "from_at": a.from_at,
            "to_at": a.to_at,
        }
        for a, worker_code, worker_name, machine_code in rows
    ]


def _active(db: Session, model, row_id: int, field: str):
    row = db.get(model, row_id)
    if not row or not getattr(row, "active", True):
        raise NotFound(f"{model.__name__} {row_id} not found", field=field)
    return row


# still on a machine in that shift: open, or (a past shift) on until its end
def _on_shift(db: Session, day: date, shift: Shift, worker_id: int) -> CrewAssignment | None:
    end = shift_window(day, shift)[1]
    return db.scalar(
        select(CrewAssignment)
        .where(
            CrewAssignment.date == day,
            CrewAssignment.shift_id == shift.id,
            CrewAssignment.worker_id == worker_id,
            or_(CrewAssignment.to_at.is_(None), CrewAssignment.to_at >= end),
        )
        .order_by(CrewAssignment.from_at.desc())
        .limit(1)
        .with_for_update()
    )


# a new shift's crew ends whatever is still open from earlier shifts, at their own shift end
def _close_earlier(db: Session, day: date, shift: Shift, user_id: int | None) -> None:
    start = shift_window(day, shift)[0]
    shifts = {s.id: s for s in db.scalars(select(Shift))}
    rows = db.scalars(
        select(CrewAssignment)
        .where(CrewAssignment.to_at.is_(None), CrewAssignment.date <= day)
        .order_by(CrewAssignment.id)
        .with_for_update()
    ).all()
    for row in rows:
        row_start, row_end = shift_window(row.date, shifts[row.shift_id])
        if row_start >= start:
            continue
        row.to_at = max(row_end, row.from_at + timedelta(seconds=1))
        audit.record(db, user_id, "end", "crew_assignments", row.id, "shift over")


# one placement, bounded by the shift's own window; attendance follows. Caller commits.
# a final wage run has paid these days; attendance under it cannot change
def _check_open_period(db: Session, day: date) -> None:
    if finance.period_locked(db, day):
        raise Conflict(
            f"Wages for {day.isoformat()} are final. Attendance for that day is locked",
            field="date",
            code="period_locked",
        )


def _place(
    db: Session,
    day: date,
    shift: Shift,
    worker_id: int,
    machine_id: int,
    user_id: int | None,
    at: datetime,
) -> CrewAssignment:
    _check_open_period(db, day)
    start, end = shift_window(day, shift)
    # a past shift is a record of the whole shift; a later one begins when it begins
    from_at, to_at = (start, end) if at >= end else (max(at, start), None)
    _close_earlier(db, day, shift, user_id)
    current = _on_shift(db, day, shift, worker_id)
    if current and current.machine_id == machine_id:
        raise Conflict("Worker is already on this machine", field="machine_id")
    if current and current.from_at >= from_at:
        # no time on the old machine yet: the placement was wrong, point it at the new one
        audit.record(
            db,
            user_id,
            "move",
            "crew_assignments",
            current.id,
            data={"from": current.machine_id, "to": machine_id},
        )
        current.machine_id = machine_id
        db.flush()
        return current
    if current:
        current.to_at = from_at
    assignment = CrewAssignment(
        date=day,
        shift_id=shift.id,
        worker_id=worker_id,
        machine_id=machine_id,
        from_at=from_at,
        to_at=to_at,
    )
    db.add(assignment)
    attendance = db.scalar(
        select(Attendance).where(
            Attendance.date == day,
            Attendance.shift_id == shift.id,
            Attendance.worker_id == worker_id,
        )
    )
    if not attendance:
        db.add(
            Attendance(
                date=day,
                shift_id=shift.id,
                worker_id=worker_id,
                status=AttendanceStatus.present,
                source=AttendanceSource.crew,
            )
        )
    elif attendance.status == AttendanceStatus.absent:
        # on a machine means at work; crew is the stronger fact
        attendance.status, attendance.source = AttendanceStatus.present, AttendanceSource.crew
    db.flush()
    audit.record(
        db,
        user_id,
        "move" if current else "assign",
        "crew_assignments",
        assignment.id,
        data={"worker_id": worker_id, "machine_id": machine_id},
    )
    return assignment


# put a worker on a machine; moving closes the old assignment. Writes attendance once.
def assign_crew(
    db: Session, body: CrewIn, user_id: int | None, at: datetime | None = None
) -> CrewAssignment:
    shift = _active(db, Shift, body.shift_id, "shift_id")
    _active(db, Worker, body.worker_id, "worker_id")
    _active(db, Machine, body.machine_id, "machine_id")
    when = at or datetime.now(UTC)
    assignment = _place(db, body.date, shift, body.worker_id, body.machine_id, user_id, when)
    db.commit()
    events.publish("machines", {"type": "crew", "id": body.machine_id})
    return assignment


# shift change in one tap: whoever ran a machine at the end of that shift runs it in this one
def carry_crew(db: Session, body: CarryIn, user_id: int | None, at: datetime | None = None) -> int:
    shift = _active(db, Shift, body.shift_id, "shift_id")
    before = _active(db, Shift, body.from_shift_id, "from_shift_id")
    from_start, from_end = shift_window(body.from_date, before)
    if from_start >= shift_window(body.date, shift)[0]:
        raise Unprocessable("Bring the crew from an earlier shift", field="from_shift_id")
    rows = db.scalars(
        select(CrewAssignment)
        .join(Machine, Machine.id == CrewAssignment.machine_id)
        .join(Worker, Worker.id == CrewAssignment.worker_id)
        .where(
            CrewAssignment.date == body.from_date,
            CrewAssignment.shift_id == before.id,
            or_(CrewAssignment.to_at.is_(None), CrewAssignment.to_at >= from_end),
            Machine.active,
            Worker.active,
        )
        .order_by(CrewAssignment.from_at, CrewAssignment.id)
    ).all()
    absent = set(
        db.scalars(
            select(Attendance.worker_id).where(
                Attendance.date == body.date,
                Attendance.shift_id == shift.id,
                Attendance.status == AttendanceStatus.absent,
            )
        )
    )
    last = {row.worker_id: row.machine_id for row in rows}  # latest machine per worker wins
    when = at or datetime.now(UTC)
    created = 0
    for worker_id, machine_id in last.items():
        if worker_id in absent or _on_shift(db, body.date, shift, worker_id):
            continue
        _place(db, body.date, shift, worker_id, machine_id, user_id, when)
        created += 1
    db.commit()
    events.publish("machines", {"type": "crew", "id": shift.id})
    return created


def end_crew(
    db: Session, assignment_id: int, user_id: int | None, at: datetime | None = None
) -> CrewAssignment:
    assignment = db.scalar(
        select(CrewAssignment).where(CrewAssignment.id == assignment_id).with_for_update()
    )
    if not assignment:
        raise NotFound(f"Crew assignment {assignment_id} not found")
    if assignment.to_at:
        raise Conflict("This assignment has already ended")
    assignment.to_at = at or datetime.now(UTC)
    audit.record(db, user_id, "end", "crew_assignments", assignment.id)
    db.commit()
    events.publish("machines", {"type": "crew", "id": assignment.machine_id})
    return assignment


# manual entry for staff off the machines, and corrections; reason goes in the audit row
def set_attendance(db: Session, body: AttendanceIn, user_id: int) -> Attendance:
    _check_open_period(db, body.date)
    shift = _active(db, Shift, body.shift_id, "shift_id")
    _active(db, Worker, body.worker_id, "worker_id")
    if body.status == AttendanceStatus.absent and _on_shift(db, body.date, shift, body.worker_id):
        raise Conflict(
            "This worker is on a machine this shift. Take them off first.", field="status"
        )
    row = db.scalar(
        select(Attendance)
        .where(
            Attendance.date == body.date,
            Attendance.shift_id == body.shift_id,
            Attendance.worker_id == body.worker_id,
        )
        .with_for_update()
    )
    before = row.status if row else None
    if not row:
        row = Attendance(date=body.date, shift_id=body.shift_id, worker_id=body.worker_id)
        db.add(row)
    row.status, row.source = body.status, AttendanceSource.manual
    db.flush()
    audit.record(
        db,
        user_id,
        "attendance",
        "attendance",
        row.id,
        body.reason,
        {"from": before, "to": row.status},
    )
    db.commit()
    return row
