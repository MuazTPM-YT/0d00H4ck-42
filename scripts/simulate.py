# 30 days of mill life replayed through the real services. Same seed, same month.
# Planted problems for the AI layer are listed in docs/simulation.md.
# run: make simulate          (empty DB: masters + 30 days)
#      make simulate-live     (API running: machine feed every few seconds)
import argparse
import json
import random
import sys
import time as wall
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed import seed_masters
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  registers every table
from app.core import audit
from app.core.codes import next_code
from app.core.db import SessionLocal
from app.core.enums import Source, Stage, Unit
from app.core.states import check_transition
from app.core.units import line_amount_paise, qty
from app.modules.auth.models import Role, User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.dispatch.service import DISPATCH_TRANSITIONS
from app.modules.finance.models import Invoice, InvoiceLine, InvoiceStatus, Payment, PaymentMode
from app.modules.finance.service import INVOICE_TRANSITIONS
from app.modules.inventory.models import (
    BatchStatus,
    ItemKind,
    MoveReason,
    Receipt,
    ReceiptStatus,
    Reservation,
    ReservationStatus,
    StockMove,
    YarnBatch,
)
from app.modules.inventory.service import BATCH_TRANSITIONS, RESERVATION_TRANSITIONS
from app.modules.masters.models import (
    Buyer,
    FabricType,
    Location,
    Machine,
    Shift,
    Supplier,
    Worker,
    YarnItem,
)
from app.modules.orders.models import Order, OrderStatus
from app.modules.orders.service import ORDER_TRANSITIONS, yarn_components
from app.modules.production import service as production
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.production.schemas import MachineEventIn, OutputIn, RollIn, RollProcessIn
from app.modules.quality.models import QcCheck, QcDecision, Roll, RollBatch, RollStatus
from app.modules.quality.service import ROLL_TRANSITIONS
from app.modules.workforce import service as workforce
from app.modules.workforce.models import AttendanceStatus, CrewAssignment
from app.modules.workforce.schemas import IST, AttendanceIn, CrewIn

HOUR = timedelta(hours=1)
REASONS = [
    "Warp beam snapped",
    "Weft feeder fault",
    "Motor overheating",
    "Air pressure drop",
    "Belt slip",
    "Sensor fault",
]
FABRIC_MIX = [
    ("SHIRT40", 45, (1200, 3000), (180, 195)),
    ("POPDYE", 35, (1000, 2500), (235, 250)),
    ("DRILL30", 20, (800, 2000), (205, 215)),
]
SHIRT_COLOURS = ["Raw White", "Navy", "Black"]
DYE_COLOURS = ["Maroon", "Bottle Green", "Sky Blue", "Mustard"]
SUPPLIERS = ["KSM", "SLY", "DCS"]
BAD_SUPPLIER = "SLY"  # planted 1: colour mismatch about 3x on the same looms
DECLINE_LOOM, DECLINE_DAYS, SEIZE_DAY = "LM-03", range(17, 23), 23  # planted 2
LEAKY_ORDER_NO = 5  # planted 3: fifth order gets 8% extra yarn
LONG_GAP_HOUR = 6  # planted 4: shift C -> A change idles machines 40-60 min
LATE_LOG_LOOM, LATE_LOG_DAYS = "LM-05", (8, 20)  # planted 5: counter uploads late


class Mill:
    def __init__(self, db: Session, start: datetime, end: datetime, seed: int):
        self.db, self.start, self.end = db, start, end
        self.rng = random.Random(seed)
        self.user = {u.role: u.id for u in db.scalars(select(User).order_by(User.id))}
        self.loc = {loc.code: loc.id for loc in db.scalars(select(Location))}
        self.machines = list(db.scalars(select(Machine).where(Machine.active).order_by(Machine.id)))
        self.mc = {m.code: m for m in self.machines}
        self.workers = list(db.scalars(select(Worker).where(Worker.active).order_by(Worker.id)))
        self.shifts = {s.code: s for s in db.scalars(select(Shift))}
        self.fabric = {f.code: f for f in db.scalars(select(FabricType))}
        self.fabric_by_id = {f.id: f for f in self.fabric.values()}
        self.buyers = list(db.scalars(select(Buyer).where(Buyer.active).order_by(Buyer.id)))
        self.supplier = {s.code: s for s in db.scalars(select(Supplier))}
        self.produced: dict[int, Decimal] = {}  # work order id -> logged qty
        self.uncut: dict[int, Decimal] = {}  # weaving work order id -> metres not cut yet
        self.target: dict[int, Decimal] = {}  # next roll length per loom job
        self.down_until: dict[int, datetime] = {}
        self.resume_at: dict[int, datetime] = {}
        self.qc_due: list[tuple[datetime, int]] = []
        self.payments: list[tuple[datetime, int, int]] = []
        self.orders_made = 0
        self.receipts_made = 0
        self.leaky_code: str | None = None
        self.forced_done: set[tuple[str, int]] = set()
        self.late_upload: set[int] = set()  # machines whose counter will upload late
        self.planted: dict[str, list] = {k: [] for k in ("late_logs", "seized", "leaky_order")}

    def day(self, t: datetime) -> int:
        return (t - self.start).days

    def sup(self) -> int:
        return self.user[Role.supervisor]

    # --- floor: everything below goes through the real production and workforce services

    def status(self, m: Machine) -> MachineStatus:
        return production.machine_status(self.db, m.id)

    def report(self, m: Machine, status: MachineStatus, at: datetime, reason=None) -> None:
        body = MachineEventIn(machine_id=m.id, status=status, reason=reason, source=Source.machine)
        production.report_machine_event(self.db, body, self.sup(), at)

    def job(self, m: Machine, status: WorkOrderStatus) -> WorkOrder | None:
        return self.db.scalar(
            select(WorkOrder)
            .where(WorkOrder.machine_id == m.id, WorkOrder.status == status)
            .order_by(WorkOrder.id)
            .limit(1)
        )

    def log(self, m: Machine, wo: WorkOrder, amount: Decimal, at: datetime) -> None:
        body = OutputIn(machine_id=m.id, work_order_id=wo.id, qty=amount, source=Source.machine)
        production.log_output(self.db, body, self.sup(), at)
        self.produced[wo.id] = self.produced.get(wo.id, Decimal(0)) + amount

    def crew_change(self, t: datetime) -> None:
        open_rows = self.db.scalars(
            select(CrewAssignment).where(CrewAssignment.to_at.is_(None)).order_by(CrewAssignment.id)
        ).all()
        for row in open_rows:
            workforce.end_crew(self.db, row.id, self.sup(), t)
        on, shift = workforce.current_shift(self.db, t)
        # eight workers per shift, the group rotates so everyone works about one shift a day
        offset = (self.day(t) * 3 + "ABC".index(shift.code)) * 8 % len(self.workers)
        group = (self.workers + self.workers)[offset : offset + 8]
        stations = [self.mc[c] for c in ("LM-01", "LM-02", "LM-03", "LM-04", "LM-05", "LM-06")]
        stations += [self.mc["SPN-01"], self.mc["DYE-01"]]
        for worker, machine in zip(group, stations, strict=True):
            if self.rng.random() < 0.05:
                body = AttendanceIn(
                    date=on,
                    shift_id=shift.id,
                    worker_id=worker.id,
                    status=AttendanceStatus.absent,
                    reason="Absent, no call",
                )
                workforce.set_attendance(self.db, body, self.sup())
                continue
            body = CrewIn(date=on, shift_id=shift.id, worker_id=worker.id, machine_id=machine.id)
            workforce.assign_crew(self.db, body, self.sup(), t)

    def move_one_worker(self, t: datetime) -> None:
        on, shift = workforce.current_shift(self.db, t)
        rows = self.db.scalars(
            select(CrewAssignment)
            .where(CrewAssignment.date == on, CrewAssignment.shift_id == shift.id)
            .where(CrewAssignment.to_at.is_(None))
            .order_by(CrewAssignment.id)
        ).all()
        if not rows:
            return
        row = self.rng.choice(rows)
        target = self.rng.choice([m for m in self.machines if m.id != row.machine_id])
        body = CrewIn(date=on, shift_id=shift.id, worker_id=row.worker_id, machine_id=target.id)
        workforce.assign_crew(self.db, body, self.sup(), t + timedelta(minutes=10))

    def shift_change(self, t: datetime) -> None:
        local_hour = t.astimezone(IST).hour
        for m in self.machines:
            if self.status(m) != MachineStatus.running:
                continue
            gap = (
                self.rng.randint(40, 60) if local_hour == LONG_GAP_HOUR else self.rng.randint(3, 8)
            )
            self.report(m, MachineStatus.idle, t, "Shift change")
            self.report(m, MachineStatus.running, t + timedelta(minutes=gap))
            self.resume_at[m.id] = t + timedelta(minutes=gap)
        self.crew_change(t)

    # queue ready jobs on the least busy machine of their stage; start the first in line
    def schedule(self, t: datetime) -> None:
        waiting = self.db.scalars(
            select(WorkOrder)
            .join(Order, Order.id == WorkOrder.order_id)
            .where(WorkOrder.status == WorkOrderStatus.waiting)
            .where(Order.status == OrderStatus.confirmed)
            .order_by(Order.deadline, WorkOrder.id)
        ).all()
        for wo in waiting:
            if wo.roll_id is None and wo.seq > 1:
                before = self.db.scalar(
                    select(WorkOrder.status).where(
                        WorkOrder.order_id == wo.order_id,
                        WorkOrder.seq == wo.seq - 1,
                        WorkOrder.roll_id.is_(None),
                    )
                )
                if before != WorkOrderStatus.done:
                    continue
            options = [
                m
                for m in self.machines
                if m.type == wo.stage and self.status(m) not in production.DOWNTIME
            ]
            if not options:
                continue
            load = dict(
                self.db.execute(
                    select(WorkOrder.machine_id, func.count())
                    .where(WorkOrder.status.in_(["queued", "running", "paused"]))
                    .group_by(WorkOrder.machine_id)
                ).all()
            )
            best = min(options, key=lambda m: (load.get(m.id, 0), m.id))
            production.queue_work_order(self.db, wo.id, best.id, self.sup())
            if wo.stage == Stage.weaving and wo.roll_id is None:
                issue_reserved_yarn(self, wo, t)
        for m in self.machines:
            if self.status(m) in production.DOWNTIME or m.id in self.down_until:
                continue
            if self.job(m, WorkOrderStatus.running) or self.job(m, WorkOrderStatus.paused):
                continue
            first = self.db.scalar(
                select(WorkOrder)
                .where(WorkOrder.machine_id == m.id, WorkOrder.status == WorkOrderStatus.queued)
                .order_by(WorkOrder.queue_position)
                .limit(1)
            )
            if first:
                at = max(t, self.resume_at.get(m.id, t)) + timedelta(minutes=2)
                production.start_work_order(self.db, first.id, self.sup(), at, Source.machine)
                self.resume_at[m.id] = at

    def efficiency(self, m: Machine, t: datetime) -> float:
        if m.code == DECLINE_LOOM and self.day(t) in DECLINE_DAYS:
            return 1 - 0.05 * (self.day(t) - DECLINE_DAYS.start + 1)
        return 1.0

    def breakdown_chance(self, m: Machine, t: datetime) -> float:
        if m.code == DECLINE_LOOM and self.day(t) in DECLINE_DAYS:
            return 0.0
        return 0.004

    # planted stoppages: first hour on or after the set time when the machine has a job
    def forced_breakdown(self, m: Machine, t: datetime) -> tuple[str, int] | None:
        hour, d = t.astimezone(IST).hour, self.day(t)
        plan = None
        if m.code == DECLINE_LOOM and d == SEIZE_DAY and hour >= 9:
            plan = ("Main shaft bearing seized", 10)
        elif m.code == LATE_LOG_LOOM and d in LATE_LOG_DAYS and hour >= 11:
            plan = ("Take-up roller jam", 3)
        elif m.code == "DYE-02" and d == 12 and hour >= 7:
            plan = ("Scheduled boiler service", 6)
        if not plan or (m.code, d) in self.forced_done:
            return None
        self.forced_done.add((m.code, d))
        return plan

    def repair(self, m: Machine, t: datetime) -> datetime | None:
        until = self.down_until.get(m.id)
        if not until or until >= t + HOUR:
            return None
        at = max(until, t)
        paused = self.job(m, WorkOrderStatus.paused)
        self.report(m, MachineStatus.running if paused else MachineStatus.idle, at)
        del self.down_until[m.id]
        if m.id in self.late_upload and paused:
            self.late_upload.discard(m.id)
            # counter buffered during the stoppage and uploads now, stamped inside the breakdown
            stamp = at - timedelta(minutes=70)
            self.log(m, paused, Decimal("6.000"), stamp)
            self.planted["late_logs"].append({"machine": m.code, "at": stamp.isoformat()})
        return at if paused else None

    def run_machine(self, m: Machine, t: datetime) -> None:
        begin = self.repair(m, t) or t
        if m.id in self.down_until:
            self.move_off_broken(m, t)
            return
        wo = self.job(m, WorkOrderStatus.running)
        if not wo:
            return
        begin = max(begin, self.resume_at.get(m.id, t))
        end = t + HOUR
        forced = self.forced_breakdown(m, t)
        broke = None
        if forced:
            broke = (*forced, t + timedelta(minutes=self.rng.randint(10, 40)))
            if m.code == LATE_LOG_LOOM:
                self.late_upload.add(m.id)
        elif self.rng.random() < self.breakdown_chance(m, t):
            hours = self.rng.randint(1, 5)
            broke = (
                self.rng.choice(REASONS),
                hours,
                t + timedelta(minutes=self.rng.randint(5, 55)),
            )
        if broke:
            end = max(broke[2], begin + timedelta(minutes=1))
        minutes = Decimal((end - begin).total_seconds() / 60)
        if minutes > 0:
            self.work(m, wo, minutes, end - timedelta(seconds=30))
        if broke and self.status(m) == MachineStatus.running:
            reason, hours, at = broke
            status = MachineStatus.maintenance if "service" in reason else MachineStatus.breakdown
            self.report(m, status, end, reason)
            self.down_until[m.id] = end + timedelta(hours=hours)
            if reason.startswith("Main shaft"):
                self.planted["seized"].append({"machine": m.code, "at": end.isoformat()})

    # long breakdown: the supervisor moves the paused job to a free machine of the same type
    def move_off_broken(self, m: Machine, t: datetime) -> None:
        paused = self.job(m, WorkOrderStatus.paused)
        if not paused or self.down_until[m.id] - t < timedelta(hours=3):
            return
        for other in self.machines:
            free = not self.job(other, WorkOrderStatus.running) and not self.job(
                other, WorkOrderStatus.paused
            )
            if (
                other.type == m.type
                and other.id != m.id
                and other.id not in self.down_until
                and free
            ):
                reason = f"{m.code} down, moved to {other.code}"
                production.move_work_order(self.db, paused.id, other.id, reason, self.sup())
                start = max(t, self.resume_at.get(other.id, t)) + timedelta(minutes=5)
                production.start_work_order(self.db, paused.id, self.sup(), start, Source.manual)
                self.resume_at[other.id] = start
                return

    def work(self, m: Machine, wo: WorkOrder, minutes: Decimal, at: datetime) -> None:
        if wo.stage == Stage.dyeing or wo.roll_id:
            self.process_rolls(m, wo, minutes, at)
            return
        made = self.produced.get(wo.id, Decimal(0))
        rate = Decimal(str(self.efficiency(m, at) * self.rng.uniform(0.88, 1.0)))
        amount = qty(min(m.rated_output_per_hour * minutes / 60 * rate, wo.planned_qty - made))
        if amount > 0:
            self.log(m, wo, amount, at)
        if wo.stage == Stage.weaving:
            self.uncut[wo.id] = self.uncut.get(wo.id, Decimal(0)) + max(amount, Decimal(0))
            while self.uncut[wo.id] >= self.target.setdefault(wo.id, self.roll_length()):
                self.cut(wo, self.target.pop(wo.id), at)
        if self.produced.get(wo.id, Decimal(0)) >= wo.planned_qty:
            if wo.stage == Stage.weaving and self.uncut.get(wo.id, 0) >= 1:
                self.cut(wo, self.uncut[wo.id], at)
            production.finish_work_order(self.db, wo.id, self.sup(), at, Source.machine)

    def roll_length(self) -> Decimal:
        return Decimal(self.rng.randint(55, 65))

    def cut(self, wo: WorkOrder, length: Decimal, at: datetime) -> None:
        roll = production.cut_roll(
            self.db, RollIn(work_order_id=wo.id, length_m=length, source=Source.machine), None, at
        )
        self.uncut[wo.id] -= length
        if roll["status"] == RollStatus.awaiting_qc:
            self.qc_due.append((at + timedelta(hours=self.rng.randint(2, 8)), roll["id"]))

    # dyeing and rework take whole rolls: as many as the hour's capacity allows
    def process_rolls(self, m: Machine, wo: WorkOrder, minutes: Decimal, at: datetime) -> None:
        if wo.roll_id:
            todo = [self.db.get(Roll, wo.roll_id)]
        else:
            todo = self.db.scalars(
                select(Roll)
                .where(Roll.order_id == wo.order_id, Roll.status == RollStatus.in_process)
                .order_by(Roll.id)
            ).all()
        room = m.rated_output_per_hour * minutes / 60
        for roll in todo:
            if roll.length_m > room and room < m.rated_output_per_hour / 2:
                break
            room -= roll.length_m
            body = RollProcessIn(work_order_id=wo.id, source=Source.machine)
            result = production.process_roll(self.db, roll.id, body, None, at)
            self.produced[wo.id] = self.produced.get(wo.id, Decimal(0)) + roll.length_m
            if result["status"] == RollStatus.awaiting_qc:
                self.qc_due.append((at + timedelta(hours=self.rng.randint(2, 8)), roll.id))
        if wo.roll_id:
            finished = todo[0].status != RollStatus.rework
        else:
            weaving_open = self.db.scalar(
                select(func.count()).where(
                    WorkOrder.order_id == wo.order_id,
                    WorkOrder.stage == Stage.weaving,
                    WorkOrder.roll_id.is_(None),
                    WorkOrder.status != WorkOrderStatus.done,
                )
            )
            rolls_left = self.db.scalar(
                select(func.count()).where(
                    Roll.order_id == wo.order_id, Roll.status == RollStatus.in_process
                )
            )
            finished = not weaving_open and not rolls_left
        if finished:
            production.finish_work_order(self.db, wo.id, self.sup(), at, Source.machine)

    def hour(self, t: datetime) -> None:
        local = t.astimezone(IST)
        if local.hour in (6, 14, 22):
            self.shift_change(t)
        if local.hour in (9, 17, 1) and self.rng.random() < 0.15:
            self.move_one_worker(t)
        if local.hour == 10:
            for _ in range(3 if self.day(t) == 0 else 1 + int(self.rng.random() < 0.3)):
                new_order(self, t)
        self.schedule(t)
        for m in self.machines:
            self.run_machine(m, t)
        due = sorted(d for d in self.qc_due if d[0] < t + HOUR)
        self.qc_due = [d for d in self.qc_due if d[0] >= t + HOUR]
        for at, roll_id in due:
            qc_decision(self, roll_id, at)
        if local.hour == 16:
            dispatch_ready(self, t)
        paid = [p for p in self.payments if p[0] < t + HOUR]
        self.payments = [p for p in self.payments if p[0] >= t + HOUR]
        for at, invoice_id, amount in paid:
            receive_payment(self, invoice_id, amount, at)
        self.resume_at = {k: v for k, v in self.resume_at.items() if v > t + HOUR}

    def run(self) -> None:
        for m in self.machines:
            self.report(m, MachineStatus.idle, self.start - timedelta(minutes=30))
        t = self.start
        while t + HOUR <= self.end:
            self.hour(t)
            t += HOUR


# --- stand-ins for other modules' services. Each writes the same ledger rows, statuses
# --- (through the owner's transition map) and audit rows as the real service will, and
# --- is swapped for the real call when that module lands.


def _store_balance(db: Session, batch_id: int, location_id: int) -> Decimal:
    into = db.scalar(
        select(func.coalesce(func.sum(StockMove.qty), 0)).where(
            StockMove.yarn_batch_id == batch_id, StockMove.to_location_id == location_id
        )
    )
    out = db.scalar(
        select(func.coalesce(func.sum(StockMove.qty), 0)).where(
            StockMove.yarn_batch_id == batch_id, StockMove.from_location_id == location_id
        )
    )
    return into - out


# store balance minus active reservations: what a new order may still claim
def _batch_free(mill: Mill, batch_id: int) -> Decimal:
    reserved = mill.db.scalar(
        select(func.coalesce(func.sum(Reservation.kg), 0)).where(
            Reservation.yarn_batch_id == batch_id, Reservation.status == ReservationStatus.active
        )
    )
    return _store_balance(mill.db, batch_id, mill.loc["YS-01"]) - reserved


def _free_batches(mill: Mill, item_id: int) -> list[tuple[YarnBatch, Decimal]]:
    batches = mill.db.scalars(
        select(YarnBatch)
        .where(YarnBatch.yarn_item_id == item_id, YarnBatch.status == BatchStatus.approved)
        .order_by(YarnBatch.id)
        .with_for_update()
    ).all()
    free = [(b, _batch_free(mill, b.id)) for b in batches]
    return [(b, kg) for b, kg in free if kg > 0]


def _move(mill, kind, item_id, amount, frm, to, reason, at, ref, user, source=Source.manual):
    mill.db.add(
        StockMove(
            at=at,
            item_kind=kind,
            yarn_batch_id=item_id if kind == ItemKind.yarn else None,
            roll_id=item_id if kind == ItemKind.fabric else None,
            qty=qty(amount),
            unit=Unit.kg if kind == ItemKind.yarn else Unit.m,
            from_location_id=mill.loc[frm],
            to_location_id=mill.loc[to],
            reason=reason,
            ref_type=ref[0],
            ref_id=ref[1],
            user_id=user,
            source=source,
        )
    )


# TODO(swap): inventory receive + approve services (Ammaar)
def receive_yarn(mill: Mill, item: YarnItem, kg: Decimal, at: datetime) -> None:
    db, rng = mill.db, mill.rng
    supplier = mill.supplier[SUPPLIERS[mill.receipts_made % len(SUPPLIERS)]]
    mill.receipts_made += 1
    rate = rng.randint(26500, 31500)
    receipt = Receipt(
        code=next_code(db, "RC"),
        supplier_id=supplier.id,
        vehicle_no=f"TN-{rng.randint(10, 99)}-{rng.choice('ABCDE')}-{rng.randint(1000, 9999)}",
        bill_no=f"{supplier.code}/{rng.randint(1000, 9999)}",
        bill_amount_paise=line_amount_paise(rate, kg),
        status=ReceiptStatus.confirmed,
        confirmed_at=at,
    )
    db.add(receipt)
    db.flush()
    audit.record(db, mill.user[Role.store], "confirmed", "receipts", receipt.id)
    batch = YarnBatch(
        code=next_code(db, "YB"),
        yarn_item_id=item.id,
        supplier_id=supplier.id,
        supplier_lot=f"{supplier.code}-L{rng.randint(1000, 9999)}",
        receipt_id=receipt.id,
        received_kg=kg,
        unit_cost_paise_per_kg=rate,
        status=BatchStatus.inspection,
    )
    db.add(batch)
    db.flush()
    ref = ("receipt", receipt.id)
    _move(mill, ItemKind.yarn, batch.id, kg, "SUP", "INSP", MoveReason.receipt, at, ref, None)
    check_transition(BATCH_TRANSITIONS, batch.status, BatchStatus.approved)
    batch.status = BatchStatus.approved
    approved = at + timedelta(hours=3)
    ref = ("yarn_batch", batch.id)
    _move(
        mill, ItemKind.yarn, batch.id, kg, "INSP", "YS-01", MoveReason.approve, approved, ref, None
    )
    audit.record(db, mill.user[Role.store], "approved", "yarn_batches", batch.id)
    db.commit()


# TODO(swap): orders create + confirm services (Ammaar), then inventory.reserve
def new_order(mill: Mill, t: datetime) -> None:
    db, rng = mill.db, mill.rng
    code, _, (lo, hi), (r_lo, r_hi) = rng.choices(FABRIC_MIX, weights=[f[1] for f in FABRIC_MIX])[0]
    fabric = mill.fabric[code]
    colour = (
        "Raw White"
        if code == "DRILL30"
        else rng.choice(DYE_COLOURS if code == "POPDYE" else SHIRT_COLOURS)
    )
    order = Order(
        code=next_code(db, "SO"),
        buyer_id=rng.choice(mill.buyers).id,
        fabric_type_id=fabric.id,
        colour=colour,
        qty_m=Decimal(rng.randrange(lo, hi + 1, 100)),
        rate_paise_per_m=rng.randint(r_lo, r_hi) * 100,
        deadline=(t + timedelta(days=rng.randint(12, 25))).astimezone(IST).date(),
        status=OrderStatus.draft,
    )
    db.add(order)
    db.flush()
    audit.record(db, mill.user[Role.sales], "create", "orders", order.id)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.confirmed)
    order.status, order.confirmed_at = OrderStatus.confirmed, t
    audit.record(db, mill.user[Role.sales], "confirmed", "orders", order.id)
    production.create_work_orders(db, order.id, mill.user[Role.sales])
    db.commit()
    mill.orders_made += 1
    if mill.orders_made == LEAKY_ORDER_NO:
        mill.leaky_code = order.code
    reserve_yarn(mill, order, t)


# TODO(swap): inventory.reserve (Ammaar)
def reserve_yarn(mill: Mill, order: Order, t: datetime) -> None:
    db = mill.db
    fabric = mill.fabric_by_id[order.fabric_type_id]
    spare = Decimal("1.08") if order.code == mill.leaky_code else Decimal(1)
    for line in yarn_components(order.qty_m, fabric, order.colour):
        item = db.scalar(
            select(YarnItem).filter_by(
                fibre=line["fibre"], count=line["count"], colour=line["colour"]
            )
        )
        if not item:
            item = YarnItem(fibre=line["fibre"], count=line["count"], colour=line["colour"])
            db.add(item)
            db.flush()
        need = line["kg_needed"]
        free = sum((f for _, f in _free_batches(mill, item.id)), Decimal(0))
        if free < need * spare:
            lot = Decimal(((int(need * spare - free) // 500) + 1) * 500 + 500)
            receive_yarn(mill, item, lot, t - timedelta(hours=6))
        for batch, free in _free_batches(mill, item.id):
            take = qty(min(free, need))
            db.add(Reservation(yarn_batch_id=batch.id, order_id=order.id, kg=take))
            need -= take
            if need <= 0:
                break
    audit.record(db, mill.user[Role.store], "reserve", "orders", order.id)
    db.commit()


# TODO(swap): inventory.issue_to_work_order (Ammaar)
def issue_reserved_yarn(mill: Mill, wo: WorkOrder, t: datetime) -> None:
    db = mill.db
    leaky = db.get(Order, wo.order_id).code == mill.leaky_code
    rows = db.scalars(
        select(Reservation)
        .where(Reservation.order_id == wo.order_id, Reservation.status == ReservationStatus.active)
        .order_by(Reservation.id)
    ).all()
    for r in rows:
        kg = r.kg
        extra = qty(r.kg * Decimal("0.08"))
        if leaky and _batch_free(mill, r.yarn_batch_id) >= extra:
            kg += extra
            audit.record(
                db,
                mill.user[Role.store],
                "over_issue",
                "work_orders",
                wo.id,
                "Extra for broken ends",
                {"kg": str(extra)},
            )
            mill.planted["leaky_order"].append(
                {"order": mill.leaky_code, "work_order": wo.code, "extra_kg": str(extra)}
            )
        ref = ("work_order", wo.id)
        _move(
            mill,
            ItemKind.yarn,
            r.yarn_batch_id,
            kg,
            "YS-01",
            "WIP",
            MoveReason.issue,
            t,
            ref,
            mill.user[Role.store],
            Source.scanner,
        )
        check_transition(RESERVATION_TRANSITIONS, r.status, ReservationStatus.consumed)
        r.status = ReservationStatus.consumed
    db.commit()


# TODO(swap): quality QC decision service (Razan); rework goes through the real
# production.create_rework_work_order
def qc_decision(mill: Mill, roll_id: int, at: datetime) -> None:
    db, rng = mill.db, mill.rng
    roll = db.get(Roll, roll_id)
    attempt = db.scalar(select(func.count()).where(QcCheck.roll_id == roll.id)) + 1
    suppliers = set(
        db.scalars(
            select(YarnBatch.supplier_id)
            .join(RollBatch, RollBatch.yarn_batch_id == YarnBatch.id)
            .where(RollBatch.roll_id == roll.id)
        )
    )
    bad = mill.supplier[BAD_SUPPLIER].id in suppliers
    damp = 0.3 if attempt > 1 else 1.0
    defects = []
    if rng.random() < 0.03 * (3 if bad else 1) * damp:
        defects.append({"type": "colour_mismatch", "count": 1})
    if rng.random() < 0.025 * damp:
        defects.append({"type": "hole", "count": rng.randint(1, 3)})
    if rng.random() < 0.02 * damp:
        defects.append({"type": "uneven_weave", "count": rng.randint(1, 4)})
    kinds = {d["type"] for d in defects}
    if not defects:
        decision = QcDecision.pass_
    elif attempt > 1 or ("colour_mismatch" in kinds and rng.random() < 0.6):
        decision = QcDecision.reject
    else:
        decision = QcDecision.rework
    band = rng.choices("ABC", weights=[70, 25, 5])[0] if decision == QcDecision.pass_ else None
    fabric = mill.fabric_by_id[
        db.scalar(select(Order.fabric_type_id).where(Order.id == roll.order_id))
    ]
    db.add(
        QcCheck(
            roll_id=roll.id,
            inspector_id=mill.user[Role.qc],
            at=at,
            attempt_no=attempt,
            decision=decision,
            defects=defects,
            shade_band=band,
            gsm=fabric.gsm + Decimal(rng.randint(-3, 3)) if band else None,
            width_cm=fabric.width_cm if band else None,
        )
    )
    new = {
        QcDecision.pass_: RollStatus.passed,
        QcDecision.rework: RollStatus.rework,
        QcDecision.reject: RollStatus.rejected,
    }[decision]
    check_transition(ROLL_TRANSITIONS, roll.status, new)
    audit.record(db, mill.user[Role.qc], str(new), "rolls", roll.id, data={"attempt": attempt})
    roll.status = new
    if new == RollStatus.passed:
        roll.shade_band, roll.passed_at, roll.location_id = band, at, mill.loc["FG-01"]
        ref = ("roll", roll.id)
        _move(
            mill,
            ItemKind.fabric,
            roll.id,
            roll.length_m,
            "WIP",
            "FG-01",
            MoveReason.qc_pass,
            at,
            ref,
            mill.user[Role.qc],
        )
    elif new == RollStatus.rejected:
        roll.location_id = mill.loc["REJ"]
        ref = ("roll", roll.id)
        _move(
            mill,
            ItemKind.fabric,
            roll.id,
            roll.length_m,
            "WIP",
            "REJ",
            MoveReason.qc_reject,
            at,
            ref,
            mill.user[Role.qc],
        )
    else:
        stage = fabric.stages[-1].stage
        production.create_rework_work_order(db, roll.id, stage, mill.user[Role.qc])
    db.commit()


# TODO(swap): dispatch create/load/confirm services (Ashil); one shade band per dispatch
def dispatch_ready(mill: Mill, t: datetime) -> None:
    db = mill.db
    orders = db.scalars(
        select(Order).where(Order.status == OrderStatus.confirmed).order_by(Order.id)
    ).all()
    for order in orders:
        open_jobs = db.scalar(
            select(func.count()).where(
                WorkOrder.order_id == order.id, WorkOrder.status != WorkOrderStatus.done
            )
        )
        pending = db.scalar(
            select(func.count()).where(
                Roll.order_id == order.id,
                Roll.status.in_([RollStatus.in_process, RollStatus.awaiting_qc, RollStatus.rework]),
            )
        )
        passed = db.scalars(
            select(Roll)
            .where(Roll.order_id == order.id, Roll.status == RollStatus.passed)
            .order_by(Roll.id)
        ).all()
        complete = open_jobs == 0 and pending == 0
        if not passed or not (complete or sum(r.length_m for r in passed) >= 1500):
            continue
        for band in sorted({r.shade_band for r in passed}):
            ship(mill, order, [r for r in passed if r.shade_band == band], t)
        if complete:
            check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.closed)
            order.status = OrderStatus.closed
            audit.record(db, mill.user[Role.dispatch], "closed", "orders", order.id)
        db.commit()


def ship(mill: Mill, order: Order, rolls: list[Roll], t: datetime) -> None:
    db, rng = mill.db, mill.rng
    d = Dispatch(
        code=next_code(db, "DN"),
        order_id=order.id,
        buyer_id=order.buyer_id,
        vehicle_no=f"KA-{rng.randint(1, 53):02d}-{rng.choice('ABCDEF')}-{rng.randint(1000, 9999)}",
        driver=rng.choice(["Ravi", "Shankar", "Iqbal", "Manju"]),
        status=DispatchStatus.draft,
    )
    db.add(d)
    db.flush()
    for new in (DispatchStatus.loading, DispatchStatus.confirmed):
        check_transition(DISPATCH_TRANSITIONS, d.status, new)
        d.status = new
    d.confirmed_at = t
    audit.record(db, mill.user[Role.dispatch], "confirmed", "dispatches", d.id)
    for r in rolls:
        db.add(DispatchRoll(dispatch_id=d.id, roll_id=r.id))
        check_transition(ROLL_TRANSITIONS, r.status, RollStatus.dispatched)
        r.status, r.location_id = RollStatus.dispatched, mill.loc["DISP"]
        ref = ("dispatch", d.id)
        _move(
            mill,
            ItemKind.fabric,
            r.id,
            r.length_m,
            "FG-01",
            "DISP",
            MoveReason.dispatch,
            t,
            ref,
            mill.user[Role.dispatch],
        )
    db.flush()
    invoice_dispatch(mill, order, d, rolls, t)


# TODO(swap): finance invoice-from-dispatch service (Ashil)
def invoice_dispatch(mill: Mill, order: Order, d: Dispatch, rolls: list[Roll], t: datetime):
    db, rng = mill.db, mill.rng
    lines = [(r, line_amount_paise(order.rate_paise_per_m, r.length_m)) for r in rolls]
    subtotal = sum(a for _, a in lines)
    tax = subtotal * 5 // 100  # GST 5% on cotton fabric (HSN 5208)
    inv = Invoice(
        code=next_code(db, "INV"),
        dispatch_id=d.id,
        buyer_id=order.buyer_id,
        order_id=order.id,
        subtotal_paise=subtotal,
        tax_paise=tax,
        total_paise=subtotal + tax,
        issued_at=t,
        due_date=t.astimezone(IST).date() + timedelta(days=30),
        status=InvoiceStatus.issued,
    )
    db.add(inv)
    db.flush()
    for r, amount in lines:
        db.add(
            InvoiceLine(
                invoice_id=inv.id,
                roll_id=r.id,
                metres=r.length_m,
                rate_paise_per_m=order.rate_paise_per_m,
                amount_paise=amount,
            )
        )
    audit.record(db, mill.user[Role.accounts], "issued", "invoices", inv.id)
    roll = rng.random()
    if roll < 0.55:
        mill.payments.append((t + timedelta(days=rng.randint(5, 20)), inv.id, inv.total_paise))
    elif roll < 0.8:
        half = inv.total_paise // 2
        mill.payments.append((t + timedelta(days=rng.randint(3, 10)), inv.id, half))
        mill.payments.append(
            (t + timedelta(days=rng.randint(12, 25)), inv.id, inv.total_paise - half)
        )


# TODO(swap): finance payment service (Ashil); invoice status follows payments
def receive_payment(mill: Mill, invoice_id: int, amount: int, at: datetime) -> None:
    db = mill.db
    inv = db.get(Invoice, invoice_id)
    paid = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.invoice_id == inv.id)
    )
    db.add(
        Payment(
            invoice_id=inv.id,
            amount_paise=amount,
            received_at=at,
            mode=mill.rng.choice([PaymentMode.bank_transfer, PaymentMode.upi, PaymentMode.cheque]),
            ref=f"NEFT{inv.id:06d}{mill.rng.randint(100, 999)}",
        )
    )
    new = InvoiceStatus.paid if paid + amount >= inv.total_paise else InvoiceStatus.part_paid
    if new != inv.status:
        check_transition(INVOICE_TRANSITIONS, inv.status, new)
        inv.status = new
    audit.record(
        db, mill.user[Role.accounts], "payment", "invoices", inv.id, data={"paise": amount}
    )
    db.commit()


# --- entry points


def simulate(db: Session, now: datetime, days: int = 30, seed: int = 42) -> dict:
    seed_masters(db)
    db.commit()
    first_day = (now.astimezone(IST) - timedelta(days=days)).date()
    start = workforce.shift_window(first_day, db.scalar(select(Shift).filter_by(code="A")))[0]
    mill = Mill(db, start, now.replace(minute=0, second=0, microsecond=0), seed)
    mill.run()
    return {"from": start.isoformat(), "to": mill.end.isoformat(), **mill.planted}


def main_month(days: int, seed: int) -> None:
    with SessionLocal() as db:
        if db.scalar(select(Order.id).limit(1)) or db.scalar(select(MachineEvent.id).limit(1)):
            sys.exit(
                "This database already has orders or machine events. The simulator writes a "
                "whole month and needs an empty one: make db-reset migrate simulate"
            )
        result = simulate(db, datetime.now(UTC), days, seed)
        counts = {
            name: db.scalar(select(func.count()).select_from(model))
            for name, model in [
                ("orders", Order),
                ("work_orders", WorkOrder),
                ("machine_events", MachineEvent),
                ("output_logs", ProductionLog),
                ("rolls", Roll),
                ("qc_checks", QcCheck),
                ("dispatches", Dispatch),
                ("invoices", Invoice),
            ]
        }
    print(json.dumps({"counts": counts, "planted": result}, indent=2))


# --- live mode: the automated-mill tier. Posts through the HTTP API like a machine gateway.


class Api:
    def __init__(self, base: str, email: str, password: str):
        self.base = base.rstrip("/")
        login = self.call("POST", "/auth/login", {"email": email, "password": password})
        self.token = login["access_token"]

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        if getattr(self, "token", None):
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read() or "null")


def live(base: str, interval: float, seed: int) -> None:
    rng = random.Random(seed)
    api = Api(base, "supervisor@everest.local", "demo1234")
    down: dict[int, int] = {}  # machine id -> ticks left in breakdown
    uncut: dict[int, float] = {}
    print(f"live feed on {base}, every {interval}s. Ctrl+C stops.")
    while True:
        for tile in api.call("GET", "/production/board")["machines"]:
            mid, job = tile["machine_id"], tile["job"]
            try:
                if mid in down:
                    down[mid] -= 1
                    if down[mid] <= 0:
                        del down[mid]
                        status = "running" if job else "idle"
                        api.call(
                            "POST",
                            "/production/machine-events",
                            {"machine_id": mid, "status": status, "source": "machine"},
                        )
                    continue
                if tile["status"] == "idle" and job and job["status"] == "paused":
                    api.call(
                        "POST",
                        "/production/machine-events",
                        {"machine_id": mid, "status": "running", "source": "machine"},
                    )
                    continue
                if (
                    tile["status"] != "running"
                    or not job
                    or job["stage"] == "dyeing"
                    or job["roll_id"]
                ):
                    continue
                if rng.random() < 0.02:
                    api.call(
                        "POST",
                        "/production/machine-events",
                        {
                            "machine_id": mid,
                            "status": "breakdown",
                            "source": "machine",
                            "reason": rng.choice(REASONS),
                        },
                    )
                    down[mid] = rng.randint(4, 10)
                    continue
                left = float(job["planned"]) - float(job["produced"])
                amount = round(min(left, rng.uniform(1.0, 2.5)), 3)
                if amount <= 0:
                    continue
                api.call(
                    "POST",
                    "/production/output",
                    {"machine_id": mid, "qty": str(amount), "source": "machine"},
                )
                if job["stage"] == "weaving":
                    uncut[mid] = uncut.get(mid, 0) + amount
                    if uncut[mid] >= 20:
                        api.call(
                            "POST",
                            "/production/rolls",
                            {
                                "work_order_id": job["work_order_id"],
                                "length_m": f"{uncut[mid]:.3f}",
                                "source": "machine",
                            },
                        )
                        uncut[mid] = 0
            except urllib.error.HTTPError as e:
                print(f"{tile['code']}: {e.code} {e.read().decode()[:160]}")
        wall.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Everest month simulator")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--live", action="store_true", help="post machine feed to a running API")
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--api", default="http://localhost:8000/api")
    args = parser.parse_args()
    if args.live:
        try:
            live(args.api, args.interval, args.seed)
        except KeyboardInterrupt:
            pass
        except urllib.error.URLError as e:
            sys.exit(f"Cannot reach the API at {args.api}: {e.reason}. Start it with make dev.")
    else:
        main_month(args.days, args.seed)
