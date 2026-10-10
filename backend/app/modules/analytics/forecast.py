import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import Stage
from app.modules.masters.models import Machine, Shift
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.production.service import DOWNTIME, FLOW, status_durations
from app.modules.workforce.schemas import IST
from app.modules.workforce.service import shift_window

SHIFTS_USED = 6  # throughput = median of the last 6 shifts the machine actually ran
MIN_RUN_HOURS = 1.0  # a shift with less running time says little about speed
QC_HOURS = 8  # rolls wait about one shift for inspection
DISPATCH_HOURS = 24  # dispatch loads once a day
AT_RISK_HOURS = 24  # less than a day of slack = at risk
DEFAULT_REPAIR_HOURS = 2.0


@dataclass
class FloorMachine:
    id: int
    code: str
    stage: Stage
    rate: float  # output per running hour, in the machine's unit
    free_at: datetime


@dataclass
class Job:
    id: int
    code: str
    order_id: int
    stage: Stage
    remaining: float
    unit: str
    deadline: date
    machine_id: int | None = None  # set for running/paused jobs: they stay where they are
    plan: dict = field(default_factory=dict)


# whole floor at once: per stage, the machine that frees up first takes the most urgent job
# ponytail: greedy EDF, not an optimal schedule; ignores the supervisor's queue order
def schedule(machines: list[FloorMachine], jobs: list[Job], now: datetime) -> dict[int, datetime]:
    by_id = {m.id: m for m in machines}
    ready: dict[int, datetime] = defaultdict(lambda: now)  # order -> earliest start of next stage
    for stage in sorted(Stage, key=FLOW.get):
        stage_jobs = [j for j in jobs if j.stage == stage]
        ends: dict[int, list[datetime]] = defaultdict(list)
        for job in (j for j in stage_jobs if j.machine_id in by_id):
            m = by_id[job.machine_id]
            start = max(m.free_at, now)
            m.free_at = start + timedelta(hours=job.remaining / m.rate)
            job.plan = {"machine": m, "start": start, "end": m.free_at}
            ends[job.order_id].append(m.free_at)
        heap = [(m.free_at, m.code, m.id) for m in machines if m.stage == stage]
        heapq.heapify(heap)
        for job in sorted(
            (j for j in stage_jobs if j.machine_id not in by_id),
            key=lambda j: (j.deadline, j.order_id, j.id),
        ):
            if not heap:
                job.plan = {}
                continue
            free_at, code, machine_id = heapq.heappop(heap)
            m = by_id[machine_id]
            start = max(free_at, ready[job.order_id])
            end = start + timedelta(hours=job.remaining / m.rate)
            heapq.heappush(heap, (end, code, machine_id))
            job.plan = {"machine": m, "start": start, "end": end}
            ends[job.order_id].append(end)
        for order_id, order_ends in ends.items():
            ready[order_id] = max([ready[order_id], *order_ends])
    return dict(ready)


def status_for(expected: datetime, deadline: date) -> tuple[str, float]:
    deadline_end = datetime.combine(deadline + timedelta(days=1), time(0), IST)
    slack = (deadline_end - expected).total_seconds() / 3600
    if slack < 0:
        return "late", slack
    return ("at_risk" if slack < AT_RISK_HOURS else "on_track"), slack


# per machine: median output per running hour over its last few full shifts
def throughputs(db: Session, now: datetime) -> dict[int, dict]:
    since = now - timedelta(days=7)
    shifts = db.scalars(select(Shift)).all()
    windows = []
    first_day = since.astimezone(IST).date()
    for d in range((now.astimezone(IST).date() - first_day).days + 1):
        for s in shifts:
            start, end = shift_window(first_day + timedelta(days=d), s)
            if start >= since and end <= now:
                windows.append((start, end))
    windows.sort(reverse=True)
    events = defaultdict(list)
    for machine_id, at, status in db.execute(
        select(MachineEvent.machine_id, MachineEvent.at, MachineEvent.status)
        .where(MachineEvent.at < now)
        .order_by(MachineEvent.machine_id, MachineEvent.at, MachineEvent.id)
    ):
        events[machine_id].append((at, status))
    logs = defaultdict(list)
    for machine_id, at, amount in db.execute(
        select(ProductionLog.machine_id, ProductionLog.at, ProductionLog.qty)
        .join(WorkOrder, WorkOrder.id == ProductionLog.work_order_id)
        .where(ProductionLog.at >= since, ProductionLog.at < now, WorkOrder.roll_id.is_(None))
    ):
        logs[machine_id].append((at, float(amount)))

    result = {}
    for m in db.scalars(select(Machine).where(Machine.active)):
        rates = []
        for start, end in windows:
            hours = status_durations(events[m.id], start, end)[MachineStatus.running] / 3600
            if hours >= MIN_RUN_HOURS:
                made = sum(q for at, q in logs[m.id] if start <= at < end)
                rates.append(made / hours)
            if len(rates) == SHIFTS_USED:
                break
        result[m.id] = (
            {"per_hour": round(median(rates), 1), "from": f"median of {len(rates)} shifts"}
            if rates
            else {"per_hour": round(float(m.rated_output_per_hour), 1), "from": "rated speed"}
        )
    return result


# median hours from a breakdown to the next status report, last 30 days
def repair_hours(db: Session, now: datetime) -> float:
    rows = db.execute(
        select(MachineEvent.machine_id, MachineEvent.at, MachineEvent.status)
        .where(MachineEvent.at >= now - timedelta(days=30), MachineEvent.at < now)
        .order_by(MachineEvent.machine_id, MachineEvent.at, MachineEvent.id)
    ).all()
    spans = [
        (b.at - a.at).total_seconds() / 3600
        for a, b in zip(rows, rows[1:], strict=False)
        if a.machine_id == b.machine_id and a.status == MachineStatus.breakdown
    ]
    return round(median(spans), 1) if spans else DEFAULT_REPAIR_HOURS


# every confirmed order's forecast in one pass, because all orders share the same machines
def estimate_all(db: Session, now: datetime) -> dict[int, dict]:
    rates = throughputs(db, now)
    repair = repair_hours(db, now)
    latest = {
        e.machine_id: e
        for e in db.scalars(
            select(MachineEvent)
            .where(MachineEvent.at <= now)
            .distinct(MachineEvent.machine_id)
            .order_by(MachineEvent.machine_id, MachineEvent.at.desc(), MachineEvent.id.desc())
        )
    }
    machines = []
    for m in db.scalars(select(Machine).where(Machine.active).order_by(Machine.code)):
        free_at = now
        event = latest.get(m.id)
        if event and event.status in DOWNTIME:
            free_at = max(now, event.at + timedelta(hours=repair))
        machines.append(FloorMachine(m.id, m.code, m.type, rates[m.id]["per_hour"], free_at))
    machines = [m for m in machines if m.rate > 0]

    orders = {
        o.id: o for o in db.scalars(select(Order).where(Order.status == OrderStatus.confirmed))
    }
    produced = dict(
        db.execute(
            select(ProductionLog.work_order_id, func.sum(ProductionLog.qty)).group_by(
                ProductionLog.work_order_id
            )
        ).all()
    )
    jobs = []
    for wo in db.scalars(
        select(WorkOrder).where(
            WorkOrder.order_id.in_(orders),
            WorkOrder.roll_id.is_(None),
            WorkOrder.status != WorkOrderStatus.done,
        )
    ):
        remaining = float(max(wo.planned_qty - produced.get(wo.id, Decimal(0)), Decimal(0)))
        pinned = wo.status in (WorkOrderStatus.running, WorkOrderStatus.paused)
        jobs.append(
            Job(
                wo.id,
                wo.code,
                wo.order_id,
                wo.stage,
                remaining,
                wo.unit,
                orders[wo.order_id].deadline,
                wo.machine_id if pinned else None,
            )
        )
    ready = schedule(machines, jobs, now)

    by_order = defaultdict(list)
    for job in jobs:
        by_order[job.order_id].append(job)
    result = {}
    for order_id, order in orders.items():
        order_jobs = sorted(by_order[order_id], key=lambda j: FLOW[j.stage])
        blocked = [j.code for j in order_jobs if not j.plan]
        expected = ready.get(order_id, now) + timedelta(hours=QC_HOURS + DISPATCH_HOURS)
        status, slack = status_for(expected, order.deadline)
        used = {j.plan["machine"].id: j.plan["machine"].code for j in order_jobs if j.plan}
        result[order_id] = {
            "order_id": order_id,
            "order_code": order.code,
            "deadline": order.deadline,
            "expected_at": None if blocked else expected,
            "status": "late" if blocked else status,
            "slack_hours": None if blocked else round(slack, 1),
            "blocked_by": blocked,
            "stages": [
                {
                    "work_order_id": j.id,
                    "code": j.code,
                    "stage": j.stage,
                    "remaining": round(j.remaining, 1),
                    "unit": j.unit,
                    "machine": j.plan["machine"].code if j.plan else None,
                    "start": j.plan.get("start"),
                    "end": j.plan.get("end"),
                }
                for j in order_jobs
            ],
            "basis": {
                "throughputs": {code: rates[mid] for mid, code in used.items()},
                "qc_hours": QC_HOURS,
                "dispatch_hours": DISPATCH_HOURS,
                "repair_hours": repair,
                "rule": "remaining ÷ median shift throughput, machines taken earliest-free, "
                "orders earliest-deadline first, plus QC and dispatch allowance",
            },
        }
    return result
