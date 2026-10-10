from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.modules.masters.models import Machine, Shift, Worker
from app.modules.workforce.models import (
    Attendance,
    AttendanceSource,
    AttendanceStatus,
    CrewAssignment,
)
from app.modules.workforce.schemas import IST, AttendanceIn, CrewIn


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


# who was on this machine at that moment (latest open assignment)
def crew_on_machine(db: Session, machine_id: int, at: datetime) -> int | None:
    return db.scalar(
        select(CrewAssignment.worker_id)
        .where(
            CrewAssignment.machine_id == machine_id,
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


# put a worker on a machine; moving closes the old assignment. Writes attendance once.
def assign_crew(
    db: Session, body: CrewIn, user_id: int | None, at: datetime | None = None
) -> CrewAssignment:
    at = at or datetime.now(UTC)
    _active(db, Shift, body.shift_id, "shift_id")
    _active(db, Worker, body.worker_id, "worker_id")
    _active(db, Machine, body.machine_id, "machine_id")
    current = db.scalar(
        select(CrewAssignment)
        .where(
            CrewAssignment.date == body.date,
            CrewAssignment.shift_id == body.shift_id,
            CrewAssignment.worker_id == body.worker_id,
            CrewAssignment.to_at.is_(None),
        )
        .with_for_update()
    )
    if current and current.machine_id == body.machine_id:
        raise Conflict("Worker is already on this machine", field="machine_id")
    if current:
        current.to_at = at
    assignment = CrewAssignment(
        date=body.date,
        shift_id=body.shift_id,
        worker_id=body.worker_id,
        machine_id=body.machine_id,
        from_at=at,
    )
    db.add(assignment)
    attendance = db.scalar(
        select(Attendance).where(
            Attendance.date == body.date,
            Attendance.shift_id == body.shift_id,
            Attendance.worker_id == body.worker_id,
        )
    )
    if not attendance:
        db.add(
            Attendance(
                date=body.date,
                shift_id=body.shift_id,
                worker_id=body.worker_id,
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
        data={"worker_id": body.worker_id, "machine_id": body.machine_id},
    )
    db.commit()
    events.publish("machines", {"type": "crew", "id": body.machine_id})
    return assignment


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
    _active(db, Shift, body.shift_id, "shift_id")
    _active(db, Worker, body.worker_id, "worker_id")
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
