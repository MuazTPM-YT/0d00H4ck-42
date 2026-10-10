from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.analytics.models import Severity
from app.modules.inventory.models import BatchStatus, ExpectedDelivery, Receipt, YarnBatch
from app.modules.masters.models import FabricType, Machine, Shift, Supplier, Worker
from app.modules.orders.models import Order
from app.modules.production.models import MachineEvent, MachineStatus, ProductionLog, WorkOrder
from app.modules.production.service import status_durations
from app.modules.quality.models import QcCheck, Roll, RollBatch
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


DETECTORS = [detect_suppliers, detect_root_cause, detect_machines]


def find_all(db: Session, now: datetime) -> list[dict]:
    return [f for detect in DETECTORS for f in detect(db, now)]
