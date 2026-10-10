from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.analytics.models import Severity
from app.modules.inventory.models import BatchStatus, ExpectedDelivery, Receipt, YarnBatch
from app.modules.masters.models import FabricType, Machine, Shift, Supplier, Worker
from app.modules.orders.models import Order
from app.modules.quality.models import QcCheck, Roll, RollBatch

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


DETECTORS = [detect_suppliers, detect_root_cause]


def find_all(db: Session, now: datetime) -> list[dict]:
    return [f for detect in DETECTORS for f in detect(db, now)]
