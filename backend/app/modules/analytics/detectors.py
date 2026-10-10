from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import Stage
from app.core.units import yarn_kg_for_fabric
from app.modules.analytics.models import Severity
from app.modules.inventory.models import (
    BatchStatus,
    ExpectedDelivery,
    ItemKind,
    MoveReason,
    Receipt,
    StockMove,
    YarnBatch,
)
from app.modules.masters.models import FabricType, Machine, Shift, Supplier, Worker
from app.modules.orders.models import Order
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    ProductionLog,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.production.service import DOWNTIME, status_durations
from app.modules.quality.models import QcCheck, Roll, RollBatch, RollEvent
from app.modules.workforce.schemas import IST
from app.modules.workforce.service import day_start

# Detector layer. Each detector reads the ledger and event tables (never writes them) and
# returns findings: {kind, severity, entity_type, entity_id, title, facts}. Facts carry the
# numbers shown to people and `records` (type, id, code) behind those numbers.
# Statistics learn each mill's own baseline from its own rows; nothing is pretrained.

LOOKBACK = timedelta(days=60)


def finding(kind, severity, entity_type, entity_id, title, facts) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": title,
        "facts": facts,
    }


def pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def label(defect: str) -> str:
    return defect.replace("_", " ")


# --- QC facts: first inspection of each roll, with everything that touched it

FACTORS = {
    "machine": "machines",
    "shift": "shifts",
    "weaver": "workers",
    "yarn_batch": "yarn_batches",
    "supplier": "suppliers",
    "fabric": "fabric_types",
}


@dataclass
class QcRoll:
    id: int
    code: str
    at: datetime
    defects: set[str]
    # factor -> {(id, code)}; batch and supplier can hold several (a roll mixes lots)
    factors: dict[str, set[tuple[int, str]]]

    @property
    def loom(self) -> int:
        return next(iter(self.factors["machine"]))[0]


def load_qc_rolls(db: Session, since: datetime) -> list[QcRoll]:
    first = (QcCheck.roll_id == Roll.id) & (QcCheck.attempt_no == 1)
    rows = db.execute(
        select(
            Roll.id,
            Roll.code,
            QcCheck.at,
            QcCheck.defects,
            Machine.id,
            Machine.code,
            Shift.id,
            Shift.code,
            Worker.id,
            Worker.code,
            FabricType.id,
            FabricType.code,
        )
        .join(QcCheck, first)
        .join(Machine, Machine.id == Roll.loom_machine_id)
        .join(Shift, Shift.id == Roll.shift_id)
        .outerjoin(Worker, Worker.id == Roll.weaver_id)
        .join(Order, Order.id == Roll.order_id)
        .join(FabricType, FabricType.id == Order.fabric_type_id)
        .where(QcCheck.at >= since)
        .order_by(QcCheck.at)
    ).all()
    lots = defaultdict(lambda: {"yarn_batch": set(), "supplier": set()})
    for roll_id, batch_id, batch_code, supplier_id, supplier_code in db.execute(
        select(RollBatch.roll_id, YarnBatch.id, YarnBatch.code, Supplier.id, Supplier.code)
        .join(YarnBatch, YarnBatch.id == RollBatch.yarn_batch_id)
        .join(Supplier, Supplier.id == YarnBatch.supplier_id)
        .join(Roll, Roll.id == RollBatch.roll_id)
        .join(QcCheck, first)
        .where(QcCheck.at >= since)
    ):
        lots[roll_id]["yarn_batch"].add((batch_id, batch_code))
        lots[roll_id]["supplier"].add((supplier_id, supplier_code))
    return [
        QcRoll(
            rid,
            code,
            at,
            {d["type"] for d in defects},
            {
                "machine": {(mid, mcode)},
                "shift": {(sid, scode)},
                "weaver": {(wid, wcode)} if wid else set(),
                "fabric": {(fid, fcode)},
                **lots[rid],
            },
        )
        for rid, code, at, defects, mid, mcode, sid, scode, wid, wcode, fid, fcode in rows
    ]


# --- supplier tracing

SUPPLIER_MIN_ROLLS, SUPPLIER_MIN_DEFECTS, SUPPLIER_MIN_LIFT = 30, 8, 1.8


# observed vs expected defects for one supplier's rolls, loom by loom, so a bad loom
# cannot make a good supplier look bad: expected = sum over looms of
# (supplier's rolls on that loom x other suppliers' defect rate on that same loom)
def supplier_lift(rolls: list[QcRoll], supplier_id: int, defect: str) -> dict | None:
    by_loom = defaultdict(lambda: {"mine": [], "rest": []})
    for r in rolls:
        side = "mine" if supplier_id in {s for s, _ in r.factors["supplier"]} else "rest"
        by_loom[r.loom][side].append(r)
    observed, expected, mine, looms = 0, 0.0, [], 0
    for group in by_loom.values():
        if not group["mine"] or not group["rest"]:
            continue  # no like-for-like comparison on this loom
        rest_rate = sum(defect in r.defects for r in group["rest"]) / len(group["rest"])
        observed += sum(defect in r.defects for r in group["mine"])
        expected += len(group["mine"]) * rest_rate
        mine += group["mine"]
        looms += 1
    if not mine:
        return None
    others = [r for g in by_loom.values() if g["mine"] for r in g["rest"]]
    return {
        "rolls": len(mine),
        "defective": observed,
        "expected": round(expected, 1),
        "lift": round(observed / expected, 1) if expected else None,
        "rate_pct": pct(observed, len(mine)),
        "others_rate_pct": pct(sum(defect in r.defects for r in others), len(others)),
        "looms": looms,
        "defective_rolls": [r for r in mine if defect in r.defects],
    }


def supplier_defects(rolls: list[QcRoll]) -> list[dict]:
    suppliers = {s for r in rolls for s in r.factors["supplier"]}
    defects = {d for r in rolls for d in r.defects}
    found = []
    for supplier_id, code in sorted(suppliers, key=lambda s: s[1]):
        for defect in sorted(defects):
            s = supplier_lift(rolls, supplier_id, defect)
            if (
                not s
                or s["rolls"] < SUPPLIER_MIN_ROLLS
                or s["defective"] < SUPPLIER_MIN_DEFECTS
                or (s["lift"] or 0) < SUPPLIER_MIN_LIFT
            ):
                continue
            bad = s.pop("defective_rolls")
            batches = {b for r in bad for b in r.factors["yarn_batch"]}
            facts = {
                "key": defect,
                "supplier": code,
                "defect": label(defect),
                **s,
                "records": [{"type": "rolls", "id": r.id, "code": r.code} for r in bad]
                + [{"type": "yarn_batches", "id": b, "code": c} for b, c in sorted(batches)],
            }
            found.append(
                finding(
                    "supplier_defects",
                    Severity.critical if s["lift"] >= 3 else Severity.warn,
                    "suppliers",
                    supplier_id,
                    f"{code} yarn: {label(defect)} {s['lift']}x on the same looms",
                    facts,
                )
            )
    return found


GATE_MIN_BATCHES, GATE_MIN_COUNT, GATE_MIN_LIFT = 5, 2, 2.0


@dataclass
class GateBatch:
    supplier_id: int
    supplier: str
    quarantined: bool  # quarantined or rejected at inspection
    short: bool  # less than the expected delivery said
    id: int
    code: str


# quarantine and short deliveries at the gate, supplier vs the rest
def gate_problems(batches: list[GateBatch]) -> list[dict]:
    found = []
    for metric in ("quarantined", "short"):
        for supplier_id, code in sorted({(b.supplier_id, b.supplier) for b in batches}):
            mine = [b for b in batches if b.supplier_id == supplier_id]
            rest = [b for b in batches if b.supplier_id != supplier_id]
            hits = [b for b in mine if getattr(b, metric)]
            rate = pct(len(hits), len(mine))
            rest_rate = pct(sum(getattr(b, metric) for b in rest), len(rest))
            lift = round(rate / rest_rate, 1) if rest_rate else None
            if (
                len(mine) < GATE_MIN_BATCHES
                or len(hits) < GATE_MIN_COUNT
                or (lift is not None and lift < GATE_MIN_LIFT)
            ):
                continue
            facts = {
                "key": f"gate_{metric}",
                "supplier": code,
                "metric": metric,
                "batches": len(mine),
                "count": len(hits),
                "rate_pct": rate,
                "others_rate_pct": rest_rate,
                "lift": lift,
                "records": [{"type": "yarn_batches", "id": b.id, "code": b.code} for b in hits],
            }
            found.append(
                finding(
                    "supplier_defects",
                    Severity.warn,
                    "suppliers",
                    supplier_id,
                    f"{code}: {len(hits)} of {len(mine)} batches {metric}",
                    facts,
                )
            )
    return found


def load_gate(db: Session, since: datetime) -> list[GateBatch]:
    rows = db.execute(
        select(
            YarnBatch.supplier_id,
            Supplier.code,
            YarnBatch.status,
            YarnBatch.received_kg,
            ExpectedDelivery.expected_kg,
            YarnBatch.id,
            YarnBatch.code,
        )
        .join(Supplier, Supplier.id == YarnBatch.supplier_id)
        .join(Receipt, Receipt.id == YarnBatch.receipt_id)
        .outerjoin(ExpectedDelivery, ExpectedDelivery.id == Receipt.expected_delivery_id)
        .where(Receipt.confirmed_at >= since)
    ).all()
    return [
        GateBatch(
            sid,
            code,
            status in (BatchStatus.quarantined, BatchStatus.rejected),
            expected is not None and received < expected,
            bid,
            bcode,
        )
        for sid, code, status, received, expected, bid, bcode in rows
    ]


def detect_suppliers(db: Session, now: datetime) -> list[dict]:
    since = now - LOOKBACK
    return supplier_defects(load_qc_rolls(db, since)) + gate_problems(load_gate(db, since))


# --- defect root cause

WINDOW, BASELINE = timedelta(days=7), timedelta(days=21)
RISE, MIN_EXCESS, CAUSE_MIN_ROLLS, CAUSE_MIN_LIFT = 1.3, 5, 10, 1.5


# defect rate rose this week: which machine, shift, weaver, lot, supplier or fabric explains
# most of the extra defective rolls (share of excess), and how much worse it is (lift)
def bad(r: QcRoll) -> bool:
    return bool(r.defects)


def root_causes(rolls: list[QcRoll], now: datetime) -> dict | None:
    window = [r for r in rolls if r.at >= now - WINDOW]
    base = [r for r in rolls if now - WINDOW - BASELINE <= r.at < now - WINDOW]
    if len(window) < 20 or len(base) < 30:
        return None
    rate, base_rate = sum(map(bad, window)) / len(window), sum(map(bad, base)) / len(base)
    excess = sum(map(bad, window)) - len(window) * base_rate
    if rate < RISE * base_rate or excess < MIN_EXCESS:
        return None
    causes = []
    for factor in FACTORS:
        for value in {v for r in window for v in r.factors[factor]}:
            hit = [r for r in window if value in r.factors[factor]]
            rest = [r for r in window if value not in r.factors[factor]]
            if len(hit) < CAUSE_MIN_ROLLS or not rest:
                continue
            hit_rate, rest_rate = sum(map(bad, hit)) / len(hit), sum(map(bad, rest)) / len(rest)
            lift = hit_rate / rest_rate if rest_rate else float("inf")
            share = (sum(map(bad, hit)) - len(hit) * base_rate) / excess
            if lift >= CAUSE_MIN_LIFT and share > 0:
                causes.append((share, lift, factor, value, hit))
    if not causes:
        return None
    causes.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
    top = causes[:3]
    _, _, factor, (entity_id, code), hit = top[0]
    facts = {
        "key": "",
        "window_days": WINDOW.days,
        "rolls": len(window),
        "defective": sum(map(bad, window)),
        "rate_pct": pct(sum(map(bad, window)), len(window)),
        "baseline_rate_pct": round(100 * base_rate, 1),
        "excess": round(excess, 1),
        "causes": [
            {
                "factor": f.replace("_", " "),
                "value": c,
                "rolls": len(h),
                "defective": sum(map(bad, h)),
                "rate_pct": pct(sum(map(bad, h)), len(h)),
                "lift": round(lift, 1) if lift != float("inf") else None,
                "share_pct": round(100 * share, 1),
            }
            for share, lift, f, (_, c), h in top
        ],
        "records": [{"type": "rolls", "id": r.id, "code": r.code} for r in hit if bad(r)],
    }
    return finding(
        "defect_root_cause",
        Severity.critical if facts["causes"][0]["share_pct"] >= 50 else Severity.warn,
        FACTORS[factor],
        entity_id,
        f"Defects up to {facts['rate_pct']}%: {factor.replace('_', ' ')} {code} leads",
        facts,
    )


def detect_root_cause(db: Session, now: datetime) -> list[dict]:
    found = root_causes(load_qc_rolls(db, now - WINDOW - BASELINE), now)
    return [found] if found else []


# --- machines: slowdowns (robust z on own history), breakdown clusters, shift-change idle

MIN_DAY_HOURS = 2.0
SLOW_Z, SLOW_DAYS = -3.0, 3
MAD_TO_SIGMA = 1.4826  # MAD x 1.4826 ~ standard deviation for normal data


# median and MAD ignore outliers, so past breakdown days do not drag the baseline down
def robust_z(values: list[float]) -> tuple[float, list[float]]:
    mid = median(values)
    spread = max(median(abs(v - mid) for v in values) * MAD_TO_SIGMA, 0.01 * mid, 1e-9)
    return mid, [(v - mid) / spread for v in values]


# runs of at least SLOW_DAYS days in a row (days with data) far below the machine's own median
def slowdown_episodes(series: list[tuple[date, float]]) -> tuple[float, list[list[tuple]]]:
    if len(series) < 2 * SLOW_DAYS:
        return 0.0, []
    mid, zs = robust_z([v for _, v in series])
    episodes, run = [], []
    for (day, value), z in zip(series, zs, strict=True):
        if z <= SLOW_Z:
            run.append((day, value, z))
            continue
        if len(run) >= SLOW_DAYS:
            episodes.append(run)
        run = []
    if len(run) >= SLOW_DAYS:
        episodes.append(run)
    return mid, episodes


@dataclass
class MachineDays:
    id: int
    code: str
    unit: str
    series: list[tuple[date, float]]  # IST day -> output per running hour
    breakdowns: list[tuple[int, datetime, str]]  # (event id, at, reason)


def machine_slowdowns(machines: list[MachineDays]) -> list[dict]:
    found = []
    for m in machines:
        mid, episodes = slowdown_episodes(m.series)
        if not episodes:
            continue
        run = episodes[-1]
        start, end = run[0][0], run[-1][0]
        low = min(v for _, v, _ in run)
        drop = pct(mid - sum(v for _, v, _ in run) / len(run), mid)
        after = [
            b
            for b in m.breakdowns
            if start <= b[1].astimezone(IST).date() <= end + timedelta(days=3)
        ]
        facts = {
            "key": start.isoformat(),
            "machine": m.code,
            "unit": m.unit,
            "days": len(run),
            "from": start.isoformat(),
            "to": end.isoformat(),
            "baseline_per_hour": round(mid, 1),
            "low_per_hour": round(low, 1),
            "drop_pct": drop,
            "daily": [
                {"day": d.isoformat(), "per_hour": round(v, 1), "z": round(z, 1)} for d, v, z in run
            ],
            "followed_by": {"at": after[0][1].isoformat(), "reason": after[0][2]}
            if after
            else None,
            "records": [{"type": "machines", "id": m.id, "code": m.code}]
            + [{"type": "machine_events", "id": b[0], "code": b[2]} for b in after],
        }
        found.append(
            finding(
                "machine_slowdown",
                Severity.critical if after or drop >= 20 else Severity.warn,
                "machines",
                m.id,
                f"{m.code} slowed {drop}% for {len(run)} days",
                facts,
            )
        )
    return found


def _events_by_machine(db: Session, since: datetime, now: datetime) -> dict[int, list]:
    events = defaultdict(list)
    for e in db.scalars(
        select(MachineEvent)
        .where(MachineEvent.at < now)
        .order_by(MachineEvent.machine_id, MachineEvent.at, MachineEvent.id)
    ):
        events[e.machine_id].append(e)
    # keep the last event before the window: it tells the status the window starts in
    return {
        mid: [
            e
            for i, e in enumerate(rows)
            if e.at >= since or (i + 1 < len(rows) and rows[i + 1].at >= since)
        ]
        for mid, rows in events.items()
    }


def load_machine_days(db: Session, now: datetime, days: int = 30) -> list[MachineDays]:
    first = now.astimezone(IST).date() - timedelta(days=days)
    since = day_start(first)
    events = _events_by_machine(db, since, now)
    output = defaultdict(float)
    for machine_id, at, amount in db.execute(
        select(ProductionLog.machine_id, ProductionLog.at, ProductionLog.qty)
        .join(WorkOrder, WorkOrder.id == ProductionLog.work_order_id)
        .where(ProductionLog.at >= since, ProductionLog.at < now, WorkOrder.roll_id.is_(None))
    ):
        output[machine_id, at.astimezone(IST).date()] += float(amount)
    result = []
    for m in db.scalars(select(Machine).where(Machine.active).order_by(Machine.code)):
        rows = events.get(m.id, [])
        points = [(e.at, e.status) for e in rows]
        series = []
        for d in range(days + 1):
            day = first + timedelta(days=d)
            start = day_start(day)
            end = min(start + timedelta(days=1), now)
            if end <= start:
                break
            hours = status_durations(points, start, end)[MachineStatus.running] / 3600
            if hours >= MIN_DAY_HOURS:
                series.append((day, output[m.id, day] / hours))
        breakdowns = [(e.id, e.at, e.reason) for e in rows if e.status == MachineStatus.breakdown]
        result.append(MachineDays(m.id, m.code, m.output_unit, series, breakdowns))
    return result


CLUSTER_DAYS, MACHINE_CLUSTER, REASON_CLUSTER = 7, 4, 4
SHIFT_CLUSTER, SHIFT_SHARE = 8, 0.6


@dataclass
class Breakdown:
    id: int
    machine_id: int
    machine: str
    reason: str
    shift_id: int
    shift: str
    at: datetime
    hours: float


def breakdown_clusters(events: list[Breakdown], now: datetime) -> list[dict]:
    recent = [e for e in events if e.at >= now - timedelta(days=CLUSTER_DAYS)]
    week = now.astimezone(IST).strftime("%G-W%V")
    found = []

    def cluster(group: list[Breakdown], what: str, entity_type: str, entity_id: int, name: str):
        reasons = Counter(e.reason for e in group).most_common()
        facts = {
            "key": f"{what}:{week}",
            "what": what,
            "name": name,
            "count": len(group),
            "days": CLUSTER_DAYS,
            "downtime_hours": round(sum(e.hours for e in group), 1),
            "top_reason": reasons[0][0],
            "top_reason_count": reasons[0][1],
            "machines": sorted({e.machine for e in group}),
            "records": [{"type": "machine_events", "id": e.id, "code": e.machine} for e in group],
        }
        return finding(
            "breakdown_cluster",
            Severity.critical if len(group) >= 2 * MACHINE_CLUSTER else Severity.warn,
            entity_type,
            entity_id,
            f"{len(group)} breakdowns in {CLUSTER_DAYS} days: {name}",
            facts,
        )

    for (machine_id, code), group in _group(recent, lambda e: (e.machine_id, e.machine)).items():
        if len(group) >= MACHINE_CLUSTER:
            found.append(cluster(group, "machine", "machines", machine_id, code))
    for group in _group(recent, lambda e: e.reason.strip().lower()).values():
        if len(group) >= REASON_CLUSTER and len({e.machine_id for e in group}) > 1:
            busiest = Counter(e.machine_id for e in group).most_common(1)[0][0]
            found.append(cluster(group, "reason", "machines", busiest, group[0].reason))
    for (shift_id, code), group in _group(recent, lambda e: (e.shift_id, e.shift)).items():
        # a shift pattern needs several days; one bad afternoon is not a pattern
        days = {e.at.astimezone(IST).date() for e in group}
        if (
            len(group) >= SHIFT_CLUSTER
            and len(group) >= SHIFT_SHARE * len(recent)
            and len(days) >= 3
        ):
            found.append(cluster(group, "shift", "shifts", shift_id, f"shift {code}"))
    return found


def _group(items, key) -> dict:
    groups = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return groups


def _shift_of(shifts: list[Shift], at: datetime) -> Shift:
    minute = _minute_of_day(at)
    for s in shifts:
        start, end = _minute_of_day(s.start_time), _minute_of_day(s.end_time)
        if (start <= minute < end) if start < end else (minute >= start or minute < end):
            return s
    return shifts[0]


def _minute_of_day(t) -> int:
    t = t.astimezone(IST) if isinstance(t, datetime) else t
    return t.hour * 60 + t.minute


def load_breakdowns(db: Session, now: datetime) -> list[Breakdown]:
    shifts = list(db.scalars(select(Shift).order_by(Shift.start_time)))
    codes = dict(db.execute(select(Machine.id, Machine.code)).all())
    result = []
    for rows in _events_by_machine(db, now - timedelta(days=CLUSTER_DAYS), now).values():
        for e, nxt in zip(rows, [*rows[1:], None], strict=False):
            if e.status != MachineStatus.breakdown or not shifts:
                continue
            shift = _shift_of(shifts, e.at)
            hours = ((nxt.at if nxt else now) - e.at).total_seconds() / 3600
            reason = e.reason or "No reason"
            result.append(
                Breakdown(
                    e.id,
                    e.machine_id,
                    codes[e.machine_id],
                    reason,
                    shift.id,
                    shift.code,
                    e.at,
                    hours,
                )
            )
    return result


IDLE_WINDOW_MIN, IDLE_MIN_SPELLS, IDLE_MIN_MEDIAN, IDLE_RATIO = 15, 5, 20, 2.0


@dataclass
class IdleSpell:
    event_id: int
    machine: str
    at: datetime
    minutes: float


# idle stops that begin right after a shift starts: is one handover much slower than the rest?
def shift_change_idle(spells: list[IdleSpell], shifts: list[Shift], days: int) -> list[dict]:
    by_shift = {}
    for s in shifts:
        start = _minute_of_day(s.start_time)
        by_shift[s] = [
            sp for sp in spells if (_minute_of_day(sp.at) - start) % 1440 <= IDLE_WINDOW_MIN
        ]
    found = []
    order = sorted(shifts, key=lambda s: s.start_time)
    for s, mine in by_shift.items():
        others = [sp for o, group in by_shift.items() if o != s for sp in group]
        if len(mine) < IDLE_MIN_SPELLS or not others:
            continue
        mid, other_mid = median(sp.minutes for sp in mine), median(sp.minutes for sp in others)
        if mid < IDLE_MIN_MEDIAN or mid < IDLE_RATIO * other_mid:
            continue
        before = order[order.index(s) - 1]
        worst = sorted(mine, key=lambda sp: -sp.minutes)[:20]
        facts = {
            "key": s.code,
            "from_shift": before.code,
            "to_shift": s.code,
            "at": s.start_time.strftime("%H:%M"),
            "days": days,
            "spells": len(mine),
            "median_min": round(mid),
            "others_median_min": round(other_mid),
            "lost_hours": round(sum(sp.minutes - other_mid for sp in mine) / 60, 1),
            "machines": len({sp.machine for sp in mine}),
            "records": [
                {"type": "machine_events", "id": sp.event_id, "code": sp.machine} for sp in worst
            ],
        }
        found.append(
            finding(
                "shift_change_idle",
                Severity.warn,
                "shifts",
                s.id,
                f"Handover at {facts['at']}: machines idle {facts['median_min']} min",
                facts,
            )
        )
    return found


def load_idle_spells(db: Session, now: datetime, days: int = 30) -> list[IdleSpell]:
    codes = dict(db.execute(select(Machine.id, Machine.code)).all())
    spells = []
    for rows in _events_by_machine(db, now - timedelta(days=days), now).values():
        for e, nxt in zip(rows, rows[1:], strict=False):
            if e.status == MachineStatus.idle and e.at >= now - timedelta(days=days):
                spells.append(
                    IdleSpell(e.id, codes[e.machine_id], e.at, (nxt.at - e.at).total_seconds() / 60)
                )
    return spells


def detect_machines(db: Session, now: datetime) -> list[dict]:
    shifts = list(db.scalars(select(Shift)))
    return (
        machine_slowdowns(load_machine_days(db, now))
        + breakdown_clusters(load_breakdowns(db, now), now)
        + shift_change_idle(load_idle_spells(db, now), shifts, 30)
    )


# --- yarn yield: kg issued vs kg the woven fabric accounts for

YIELD_TOLERANCE_PCT, YIELD_MIN_KG, YIELD_MACHINE_MIN_JOBS = 3.0, 5.0, 3


@dataclass
class YieldJob:
    id: int
    code: str
    order_id: int
    order: str
    machine_id: int
    machine: str
    metres: float
    issued_kg: float
    expected_kg: float  # metres x width x GSM / 1000, plus the fabric's process loss
    cost_paise: float  # value of the issued yarn at each batch's GRN cost


def _gap(jobs: list[YieldJob], name: str, key: str) -> dict | None:
    issued, expected = sum(j.issued_kg for j in jobs), sum(j.expected_kg for j in jobs)
    gap = issued - expected
    gap_pct = pct(gap, expected)
    if gap_pct <= YIELD_TOLERANCE_PCT or gap < YIELD_MIN_KG:
        return None
    paise_per_kg = sum(j.cost_paise for j in jobs) / issued
    return {
        "key": key,
        "name": name,
        "jobs": len(jobs),
        "metres": round(sum(j.metres for j in jobs), 1),
        "issued_kg": round(issued, 1),
        "expected_kg": round(expected, 1),
        "gap_kg": round(gap, 1),
        "gap_pct": gap_pct,
        "tolerance_pct": YIELD_TOLERANCE_PCT,
        "value_rupees": round(gap * paise_per_kg / 100),
        "records": [{"type": "work_orders", "id": j.id, "code": j.code} for j in jobs],
    }


def yield_gaps(jobs: list[YieldJob]) -> list[dict]:
    found = []
    for (order_id, code), group in sorted(_group(jobs, lambda j: (j.order_id, j.order)).items()):
        if facts := _gap(group, code, ""):
            facts["records"].append({"type": "orders", "id": order_id, "code": code})
            found.append((order_id, "orders", facts))
    for (machine_id, code), group in sorted(
        _group(jobs, lambda j: (j.machine_id, j.machine)).items()
    ):
        if len(group) >= YIELD_MACHINE_MIN_JOBS and (facts := _gap(group, code, "machine")):
            found.append((machine_id, "machines", facts))
    return [
        finding(
            "yarn_yield_gap",
            Severity.critical if f["gap_pct"] >= 2 * YIELD_TOLERANCE_PCT else Severity.warn,
            entity_type,
            entity_id,
            f"{f['name']}: {f['gap_kg']} kg yarn unaccounted ({f['gap_pct']}%)",
            f,
        )
        for entity_id, entity_type, f in found
    ]


# finished weaving jobs only: a running job has yarn issued up front and rolls still to come
def load_yield_jobs(db: Session, now: datetime) -> list[YieldJob]:
    jobs = db.execute(
        select(WorkOrder, Order.code, Machine.code, FabricType)
        .join(Order, Order.id == WorkOrder.order_id)
        .join(FabricType, FabricType.id == Order.fabric_type_id)
        .join(Machine, Machine.id == WorkOrder.machine_id)
        .where(
            WorkOrder.stage == Stage.weaving,
            WorkOrder.roll_id.is_(None),
            WorkOrder.status == WorkOrderStatus.done,
            WorkOrder.finished_at >= now - LOOKBACK,
        )
    ).all()
    ids = [wo.id for wo, *_ in jobs]
    sign = {MoveReason.issue: 1, MoveReason.return_: -1}
    issued, cost = defaultdict(float), defaultdict(float)
    for wo_id, reason, kg, paise in db.execute(
        select(StockMove.ref_id, StockMove.reason, StockMove.qty, YarnBatch.unit_cost_paise_per_kg)
        .join(YarnBatch, YarnBatch.id == StockMove.yarn_batch_id)
        .where(
            StockMove.item_kind == ItemKind.yarn,
            StockMove.ref_type == "work_order",
            StockMove.ref_id.in_(ids),
            StockMove.reason.in_(sign),
        )
    ):
        issued[wo_id] += sign[reason] * float(kg)
        cost[wo_id] += sign[reason] * float(kg) * paise
    metres = dict(
        db.execute(
            select(Roll.work_order_id, func.sum(Roll.length_m))
            .where(Roll.work_order_id.in_(ids))
            .group_by(Roll.work_order_id)
        ).all()
    )
    return [
        YieldJob(
            wo.id,
            wo.code,
            wo.order_id,
            order_code,
            wo.machine_id,
            machine_code,
            float(metres.get(wo.id, 0)),
            issued[wo.id],
            float(
                yarn_kg_for_fabric(
                    metres.get(wo.id, 0), fabric.width_cm, fabric.gsm, fabric.process_loss_pct
                )
            ),
            cost[wo.id],
        )
        for wo, order_code, machine_code, fabric in jobs
        if issued[wo.id] > 0
    ]


def detect_yield(db: Session, now: datetime) -> list[dict]:
    return yield_gaps(load_yield_jobs(db, now))


# --- impossible data: rows that cannot all be true

ROLL_SLACK_M, RECEIPT_FACTOR, RECEIPT_MIN_HISTORY = 1.0, 3.0, 5


@dataclass
class Downtime:
    machine_id: int
    machine: str
    event_id: int
    status: str
    reason: str
    start: datetime
    end: datetime


@dataclass
class OutputLog:
    id: int
    machine_id: int
    at: datetime
    qty: float
    unit: str


# output stamped inside a breakdown or maintenance window: the machine was stopped then
def logs_in_downtime(windows: list[Downtime], logs: list[OutputLog]) -> list[dict]:
    by_machine = defaultdict(list)
    for w in sorted(windows, key=lambda w: w.start):
        by_machine[w.machine_id].append(w)
    found = []
    for log in logs:
        mine = by_machine.get(log.machine_id, [])
        i = bisect_right([w.start for w in mine], log.at) - 1
        if i < 0 or not (mine[i].start <= log.at < mine[i].end):
            continue
        w = mine[i]
        facts = {
            "key": "",
            "check": "output_in_downtime",
            "machine": w.machine,
            "qty": round(log.qty, 1),
            "unit": log.unit,
            "logged_at": log.at.isoformat(),
            "status": w.status,
            "reason": w.reason,
            "down_from": w.start.isoformat(),
            "down_to": w.end.isoformat(),
            "minutes_into_stop": round((log.at - w.start).total_seconds() / 60),
            "records": [
                {"type": "machines", "id": w.machine_id, "code": w.machine},
                {"type": "machine_events", "id": w.event_id, "code": w.reason},
                {"type": "production_logs", "id": log.id, "code": f"{log.qty} {log.unit}"},
            ],
        }
        found.append(
            finding(
                "impossible_data",
                Severity.warn,
                "production_logs",
                log.id,
                f"{w.machine}: output logged during {w.status}",
                facts,
            )
        )
    return found


def load_downtime_and_logs(db: Session, now: datetime) -> tuple[list[Downtime], list[OutputLog]]:
    since = now - LOOKBACK
    codes = dict(db.execute(select(Machine.id, Machine.code)).all())
    windows = []
    for rows in _events_by_machine(db, since, now).values():
        for e, nxt in zip(rows, [*rows[1:], None], strict=False):
            if e.status in DOWNTIME:
                end = nxt.at if nxt else now
                windows.append(
                    Downtime(e.machine_id, codes[e.machine_id], e.id, e.status, e.reason, e.at, end)
                )
    logs = [
        OutputLog(i, m, at, float(q), u)
        for i, m, at, q, u in db.execute(
            select(
                ProductionLog.id,
                ProductionLog.machine_id,
                ProductionLog.at,
                ProductionLog.qty,
                ProductionLog.unit,
            ).where(ProductionLog.at >= since, ProductionLog.at < now)
        )
    ]
    return windows, logs


@dataclass
class CutRoll:
    id: int
    code: str
    work_order_id: int
    work_order: str
    machine: str
    cut_at: datetime
    length_m: float
    cut_total_m: float  # metres cut from this job up to and including this roll
    logged_total_m: float  # metres of output logged on this job up to the cut


# a roll is cut from woven fabric, and woven fabric is logged output: rolls cut from a job
# can never add up to more than the output logged on it by then
def rolls_too_long(rolls: list[CutRoll]) -> list[dict]:
    found = []
    for r in rolls:
        if r.cut_total_m <= r.logged_total_m + ROLL_SLACK_M:
            continue
        facts = {
            "key": "",
            "check": "roll_too_long",
            "roll": r.code,
            "work_order": r.work_order,
            "machine": r.machine,
            "length_m": round(r.length_m, 1),
            "cut_total_m": round(r.cut_total_m, 1),
            "logged_total_m": round(r.logged_total_m, 1),
            "records": [
                {"type": "rolls", "id": r.id, "code": r.code},
                {"type": "work_orders", "id": r.work_order_id, "code": r.work_order},
            ],
        }
        found.append(
            finding(
                "impossible_data",
                Severity.warn,
                "rolls",
                r.id,
                f"{r.code}: more metres cut than logged on {r.work_order}",
                facts,
            )
        )
    return found


def load_cut_rolls(db: Session, now: datetime) -> list[CutRoll]:
    rows = db.execute(
        select(
            Roll.id,
            Roll.code,
            Roll.work_order_id,
            WorkOrder.code,
            Machine.code,
            RollEvent.at,
            Roll.length_m,
        )
        .join(RollEvent, (RollEvent.roll_id == Roll.id) & (RollEvent.kind == "woven"))
        .join(Machine, Machine.id == Roll.loom_machine_id)
        .join(WorkOrder, WorkOrder.id == Roll.work_order_id)
        .where(RollEvent.at >= now - LOOKBACK)
        .order_by(Roll.work_order_id, RollEvent.at, Roll.id)
    ).all()
    logs = defaultdict(list)
    for wo_id, at, amount in db.execute(
        select(ProductionLog.work_order_id, ProductionLog.at, ProductionLog.qty)
        .where(ProductionLog.work_order_id.in_({r[2] for r in rows}))
        .order_by(ProductionLog.work_order_id, ProductionLog.at)
    ):
        logs[wo_id].append((at, float(amount)))
    result, cut = [], defaultdict(float)
    for rid, code, wo_id, wo_code, machine, cut_at, length in rows:
        cut[wo_id] += float(length)
        logged = sum(q for at, q in logs[wo_id] if at <= cut_at)
        result.append(
            CutRoll(rid, code, wo_id, wo_code, machine, cut_at, float(length), cut[wo_id], logged)
        )
    return result


@dataclass
class Lot:
    id: int
    code: str
    supplier_id: int
    supplier: str
    kg: float


# a receipt far outside what this supplier usually sends is often a typo (1500 typed as 15000)
def odd_receipts(lots: list[Lot]) -> list[dict]:
    found = []
    for supplier, mine in sorted(_group(lots, lambda b: b.supplier).items()):
        if len(mine) < RECEIPT_MIN_HISTORY:
            continue
        usual = median(b.kg for b in mine)
        for b in mine:
            if usual / RECEIPT_FACTOR <= b.kg <= usual * RECEIPT_FACTOR:
                continue
            facts = {
                "key": "",
                "check": "odd_receipt",
                "batch": b.code,
                "supplier": supplier,
                "kg": round(b.kg, 1),
                "usual_kg": round(usual, 1),
                "receipts": len(mine),
                "ratio": round(b.kg / usual, 1),
                "records": [{"type": "yarn_batches", "id": b.id, "code": b.code}],
            }
            found.append(
                finding(
                    "impossible_data",
                    Severity.info,
                    "yarn_batches",
                    b.id,
                    f"{b.code}: {facts['kg']} kg from {supplier}, usually {facts['usual_kg']} kg",
                    facts,
                )
            )
    return found


def load_lots(db: Session, now: datetime) -> list[Lot]:
    return [
        Lot(bid, code, sid, supplier, float(kg))
        for bid, code, sid, supplier, kg in db.execute(
            select(YarnBatch.id, YarnBatch.code, Supplier.id, Supplier.code, YarnBatch.received_kg)
            .join(Supplier, Supplier.id == YarnBatch.supplier_id)
            .join(Receipt, Receipt.id == YarnBatch.receipt_id)
            .where(Receipt.confirmed_at >= now - LOOKBACK)
        )
    ]


def detect_impossible(db: Session, now: datetime) -> list[dict]:
    return (
        logs_in_downtime(*load_downtime_and_logs(db, now))
        + rolls_too_long(load_cut_rolls(db, now))
        + odd_receipts(load_lots(db, now))
    )


DETECTORS = [detect_suppliers, detect_root_cause, detect_machines, detect_yield, detect_impossible]


def find_all(db: Session, now: datetime) -> list[dict]:
    return [f for detect in DETECTORS for f in detect(db, now)]
