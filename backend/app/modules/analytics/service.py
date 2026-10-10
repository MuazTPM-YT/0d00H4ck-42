from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.modules.analytics import detectors, explainer, forecast
from app.modules.analytics.models import Insight, InsightStatus, Severity
from app.modules.auth.models import Role, User
from app.modules.finance.models import Invoice, InvoiceStatus
from app.modules.inventory import service as inventory
from app.modules.masters.models import Machine
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import (
    MachineEvent,
    MachineStatus,
    WorkOrder,
    WorkOrderStatus,
)
from app.modules.quality.models import Roll, RollEvent, RollStatus
from app.modules.workforce.schemas import IST

INSIGHT_TRANSITIONS = {
    InsightStatus.open: {InsightStatus.acknowledged, InsightStatus.resolved},
    InsightStatus.acknowledged: {InsightStatus.resolved},
}
RISK_ORDER = {"late": 0, "at_risk": 1, "on_track": 2}
# who acts on each kind of finding; owner sees everything
KIND_ROLES = {
    "supplier_defects": {Role.store, Role.qc},
    "defect_root_cause": {Role.qc, Role.supervisor},
    "machine_slowdown": {Role.supervisor},
    "breakdown_cluster": {Role.supervisor},
    "shift_change_idle": {Role.supervisor},
    "yarn_yield_gap": {Role.store, Role.supervisor},
    "impossible_data": {Role.supervisor},
}
SEVERITY_RANK = case(
    {Severity.critical: 0, Severity.warn: 1, Severity.info: 2}, value=Insight.severity
)
DETECTOR_LOCK = 4205  # pg advisory lock id: one detector run at a time
IDLE_TOO_LONG = timedelta(minutes=30)
QC_WAIT_TOO_LONG = timedelta(hours=4)
SHELF_TOO_LONG = timedelta(days=3)
ATTENTION_LIMIT = 12
PER_KIND = 3  # a flood of one kind must not push the others off the list
# the "N more" row of each kind: what to call them, where the full list lives
MORE = {
    "delivery_risk": ("orders at risk", "/orders"),
    "low_stock": ("yarns below reorder level", "/store/stock"),
    "machine": ("machines stopped", "/floor"),
    "qc_wait": ("rolls waiting for QC", "/qc"),
    "shelf": ("rolls on the shelf", "/stock/finished"),
    "overdue_invoice": ("invoices overdue", "/finance/invoices"),
    "insight": ("open insights", "/insights"),
}
INSIGHTS_PAGE = {Role.owner, Role.supervisor}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def kinds_for(role: Role) -> list[str] | None:
    if role == Role.owner:
        return None
    return [kind for kind, roles in KIND_ROLES.items() if role in roles]


def list_insights(
    db: Session,
    page: Page,
    role: Role,
    status: InsightStatus | None = None,
    severity: Severity | None = None,
    kind: str | None = None,
    q: str | None = None,
) -> dict:
    stmt = select(Insight).order_by(SEVERITY_RANK, Insight.id.desc())
    if (kinds := kinds_for(role)) is not None:
        stmt = stmt.where(Insight.kind.in_(kinds))
    if status:
        stmt = stmt.where(Insight.status == status)
    if severity:
        stmt = stmt.where(Insight.severity == severity)
    if kind:
        stmt = stmt.where(Insight.kind == kind)
    if q and q.strip():
        stmt = stmt.where(Insight.title.ilike(f"%{q.strip()}%"))
    return paginate(db, stmt, page)


# counts for the filter rail: per status, and per severity and kind inside one status
def insight_counts(db: Session, role: Role, status: InsightStatus | None = None) -> dict:
    stmt = select(Insight.status, Insight.severity, Insight.kind, func.count()).group_by(
        Insight.status, Insight.severity, Insight.kind
    )
    if (kinds := kinds_for(role)) is not None:
        stmt = stmt.where(Insight.kind.in_(kinds))
    by_status = dict.fromkeys(InsightStatus, 0)
    by_severity = dict.fromkeys(Severity, 0)
    by_kind: dict[str, dict] = {}
    for st, sev, kind, n in db.execute(stmt):
        by_status[st] += n
        if status and st != status:
            continue
        by_severity[sev] += n
        k = by_kind.setdefault(kind, {"kind": kind, "count": 0, "critical": 0})
        k["count"] += n
        if sev == Severity.critical:
            k["critical"] += n
    return {
        "by_status": by_status,
        "by_severity": by_severity,
        "by_kind": sorted(by_kind.values(), key=lambda k: (-k["critical"], -k["count"], k["kind"])),
    }


# not found and not yours look the same, so ids do not leak other roles' findings
def get_insight(db: Session, insight_id: int, role: Role) -> Insight:
    insight = db.get(Insight, insight_id)
    kinds = kinds_for(role)
    if not insight or (kinds is not None and insight.kind not in kinds):
        raise NotFound(f"Insight {insight_id} not found")
    return insight


def set_insight_status(
    db: Session, insight_id: int, new: InsightStatus, note: str, user: User
) -> Insight:
    insight = get_insight(db, insight_id, user.role)
    check_transition(INSIGHT_TRANSITIONS, insight.status, new)
    audit.record(db, user.id, str(new), "insights", insight.id, reason=note)
    insight.status = new
    db.commit()
    events.publish("insights", {"type": "insight", "id": insight.id})
    return insight


# one live insight per finding: update it, never stack a copy; a resolved finding stays quiet
def upsert_insight(db: Session, finding: dict) -> str:
    facts = jsonable_encoder(finding["facts"])
    same = [
        i
        for i in db.scalars(
            select(Insight).where(
                Insight.kind == finding["kind"],
                Insight.entity_type == finding["entity_type"],
                Insight.entity_id == finding["entity_id"],
            )
        )
        if i.facts.get("key") == facts.get("key")
    ]
    closed = [i.id for i in same if i.status == InsightStatus.resolved]
    if closed and set(closed) - _auto_resolved(db, closed):
        return "skipped"
    live = next((i for i in same if i.status != InsightStatus.resolved), None)
    if live and live.facts == facts and live.severity == finding["severity"]:
        return "unchanged"
    narrative = explainer.narrate(finding["kind"], facts)
    if live:
        live.facts, live.narrative = facts, narrative
        live.severity, live.title = finding["severity"], finding["title"]
        return "updated"
    insight = Insight(**{**finding, "facts": facts}, narrative=narrative)
    db.add(insight)
    db.flush()
    audit.record(db, None, "detected", "insights", insight.id, data={"kind": insight.kind})
    return "created"


# insights a detector run closed itself; a person's resolve keeps the finding quiet, these do not
def _auto_resolved(db: Session, ids: list[int]) -> set[int]:
    return set(
        db.scalars(
            select(audit.AuditLog.entity_id).where(
                audit.AuditLog.entity_type == "insights",
                audit.AuditLog.entity_id.in_(ids),
                audit.AuditLog.action == str(InsightStatus.resolved),
                audit.AuditLog.user_id.is_(None),
                audit.AuditLog.data["auto"].as_boolean().is_(True),
            )
        )
    )


def _finding_id(kind: str, entity_type: str, entity_id: int, facts: dict) -> tuple:
    return kind, entity_type, entity_id, facts.get("key")


# open findings of detector kinds this run did not produce again: the problem is gone.
# find_all is all or nothing (a failing detector aborts the run), so a half run closes nothing;
# kinds no detector owns (hand-made, seeded) are left alone
def _close_gone(db: Session, findings: list[dict]) -> int:
    seen = {
        _finding_id(f["kind"], f["entity_type"], f["entity_id"], jsonable_encoder(f["facts"]))
        for f in findings
    }
    gone = [
        i
        for i in db.scalars(
            select(Insight).where(
                Insight.status == InsightStatus.open, Insight.kind.in_(list(KIND_ROLES))
            )
        )
        if _finding_id(i.kind, i.entity_type, i.entity_id, i.facts) not in seen
    ]
    for i in gone:
        check_transition(INSIGHT_TRANSITIONS, i.status, InsightStatus.resolved)
        audit.record(
            db,
            None,
            str(InsightStatus.resolved),
            "insights",
            i.id,
            reason="No longer found by the detectors",
            data={"auto": True},
        )
        i.status = InsightStatus.resolved
    return len(gone)


# all detectors over the ledger; safe to run from the loop and the button at the same time
def run_detectors(db: Session, now: datetime | None = None) -> dict:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": DETECTOR_LOCK})
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    findings = detectors.find_all(db, _now(now))
    for finding in findings:
        counts[upsert_insight(db, finding)] += 1
    db.flush()
    counts["resolved"] = _close_gone(db, findings)
    db.commit()
    if counts["created"] or counts["updated"] or counts["resolved"]:
        events.publish("insights", {"type": "run", "id": 0})
    return counts


# every confirmed order, most urgent first
def delivery_board(db: Session, now: datetime | None = None) -> list[dict]:
    rows = forecast.estimate_all(db, _now(now)).values()
    return sorted(rows, key=lambda e: (RISK_ORDER[e["status"]], e["slack_hours"] or 0))


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# projected finish = remaining work over recent throughput + QC lag; on_track | at_risk | late
def delivery_estimate(db: Session, order_id: int, now: datetime | None = None) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    if order.status != OrderStatus.confirmed:
        raise Conflict(
            f"{order.code} is {order.status}. Only confirmed orders get a delivery forecast.",
            code="not_forecastable",
        )
    return forecast.estimate_all(db, _now(now))[order_id]


def _item(kind, severity, title, detail, href, entity_type, entity_id, since=None) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "href": href,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "since": since,
    }


def _hours(td: timedelta) -> str:
    minutes = int(td.total_seconds() // 60)
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h"


# store: inventory's own rule (projected free kg under reorder level), never a second copy of it
def _low_stock(db: Session, now: datetime) -> list[dict]:
    return [
        _item(
            "low_stock",
            Severity.critical if w["level"] == "short" else Severity.warn,
            f"{w['label']} below reorder level",
            f"{w['projected_free_kg']} kg free after open orders, "
            f"reorder at {w['reorder_level_kg']} kg",
            "/store/stock",
            "yarn_items",
            w["yarn_item_id"],
        )
        for w in inventory.stock_warnings(db)
    ]


# machines with a job lined up on them, and stages with work waiting on a live order
def _work_waiting(db: Session) -> tuple[set[int], set[str]]:
    queued = db.scalars(
        select(WorkOrder.machine_id).where(
            WorkOrder.machine_id.is_not(None),
            WorkOrder.status.in_([WorkOrderStatus.queued, WorkOrderStatus.paused]),
        )
    )
    stages = db.scalars(
        select(WorkOrder.stage)
        .join(Order, Order.id == WorkOrder.order_id)
        .where(WorkOrder.status == WorkOrderStatus.waiting, Order.status == OrderStatus.confirmed)
    )
    return set(queued), set(stages)


# supervisor: machines stopped, or idle over half an hour while work waits for them
def _stopped_machines(db: Session, now: datetime) -> list[dict]:
    items = []
    queued, waiting_stages = _work_waiting(db)
    for event, code, stage in db.execute(
        select(MachineEvent, Machine.code, Machine.type)
        .join(Machine, Machine.id == MachineEvent.machine_id)
        .where(Machine.active, MachineEvent.at <= now)
        .distinct(MachineEvent.machine_id)
        .order_by(MachineEvent.machine_id, MachineEvent.at.desc(), MachineEvent.id.desc())
    ):
        waited = now - event.at
        if event.status == MachineStatus.breakdown:
            severity, title = Severity.critical, f"{code} in breakdown"
        elif event.status == MachineStatus.maintenance:
            severity, title = Severity.warn, f"{code} in maintenance"
        elif (
            event.status == MachineStatus.idle
            and waited > IDLE_TOO_LONG
            and (event.machine_id in queued or stage in waiting_stages)
        ):
            severity, title = Severity.warn, f"{code} idle"
        else:
            continue
        detail = _hours(waited) + (f": {event.reason}" if event.reason else "")
        machine_id = event.machine_id
        href = f"/floor?machine={machine_id}"
        items.append(
            _item("machine", severity, title, detail, href, "machines", machine_id, event.at)
        )
    return items


# qc: rolls waiting for inspection longer than about half a shift
def _qc_waiting(db: Session, now: datetime) -> list[dict]:
    ready_at = func.max(RollEvent.at)
    rows = db.execute(
        select(Roll.id, Roll.code, ready_at)
        .join(RollEvent, RollEvent.roll_id == Roll.id)
        .where(Roll.status == RollStatus.awaiting_qc)
        .group_by(Roll.id)
        .having(ready_at < now - QC_WAIT_TOO_LONG)
        .order_by(ready_at)
    ).all()
    return [
        _item(
            "qc_wait",
            Severity.warn,
            f"{code} waiting for QC",
            f"ready {_hours(now - at)} ago",
            f"/qc/rolls/{roll_id}",
            "rolls",
            roll_id,
            at,
        )
        for roll_id, code, at in rows
    ]


# sales and owner: confirmed orders the forecast says will miss or nearly miss the deadline
def _orders_at_risk(db: Session, now: datetime) -> list[dict]:
    return [
        _item(
            "delivery_risk",
            Severity.critical if e["status"] == "late" else Severity.warn,
            f"{e['order_code']} {'will be late' if e['status'] == 'late' else 'at risk'}",
            f"due {e['deadline']:%d %b}, forecast "
            + (f"{e['expected_at'].astimezone(IST):%d %b %H:%M}" if e["expected_at"] else "none"),
            f"/orders/{e['order_id']}",
            "orders",
            e["order_id"],
        )
        for e in delivery_board(db, now)
        if e["status"] != "on_track"
    ]


# dispatch: passed rolls sitting on the shelf for days
def _shelf(db: Session, now: datetime) -> list[dict]:
    rows = db.execute(
        select(Roll.id, Roll.code, Roll.passed_at)
        .where(Roll.status == RollStatus.passed, Roll.passed_at < now - SHELF_TOO_LONG)
        .order_by(Roll.passed_at)
    ).all()
    return [
        _item(
            "shelf",
            Severity.info,
            f"{code} on shelf",
            f"passed {_hours(now - at)} ago",
            "/stock/finished",
            "rolls",
            roll_id,
            at,
        )
        for roll_id, code, at in rows
    ]


# accounts and owner: unpaid invoices past their due date
def _overdue(db: Session, now: datetime) -> list[dict]:
    today = now.astimezone(IST).date()
    rows = db.execute(
        select(Invoice.id, Invoice.code, Invoice.due_date)
        .where(Invoice.status != InvoiceStatus.paid, Invoice.due_date < today)
        .order_by(Invoice.due_date)
    ).all()
    return [
        _item(
            "overdue_invoice",
            Severity.warn,
            f"{code} overdue",
            f"due {due:%d %b}, {(today - due).days} days late",
            f"/finance/invoices?open={invoice_id}",
            "invoices",
            invoice_id,
        )
        for invoice_id, code, due in rows
    ]


def _open_insights(db: Session, role: Role) -> list[dict]:
    stmt = select(Insight).where(Insight.status == InsightStatus.open)
    if (kinds := kinds_for(role)) is not None:
        stmt = stmt.where(Insight.kind.in_(kinds))
    return [
        _item("insight", i.severity, i.title, i.narrative, f"/insights?id={i.id}", "insights", i.id)
        for i in db.scalars(stmt.order_by(SEVERITY_RANK, Insight.id.desc()))
    ]


ATTENTION_RULES = {
    Role.store: [_low_stock],
    Role.supervisor: [_stopped_machines],
    Role.qc: [_qc_waiting],
    Role.dispatch: [_shelf],
    Role.accounts: [_orders_at_risk, _overdue],
    Role.owner: [_orders_at_risk, _low_stock, _overdue],
}
RANK = {Severity.critical: 0, Severity.warn: 1, Severity.info: 2}


# everything this role should act on, worst first, uncapped
def _all_items(db: Session, role: Role, now: datetime) -> list[dict]:
    items = [item for rule in ATTENTION_RULES[role] for item in rule(db, now)]
    items += _open_insights(db, role)
    return sorted(items, key=lambda i: (RANK[i["severity"]], i["since"] or now))


# at most PER_KIND of one kind; the rest fold into one "N more" row linking to the full list
def _per_kind(items: list[dict], role: Role) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for i in items:
        groups[i["kind"]].append(i)
    out = []
    for kind, group in groups.items():
        out += group[:PER_KIND]
        hidden = group[PER_KIND:]
        noun, href = MORE.get(kind, (None, None))
        if hidden and noun and (kind != "insight" or role in INSIGHTS_PAGE):
            worst = min((i["severity"] for i in hidden), key=RANK.get)
            out.append(_item("more", worst, f"{len(hidden)} more {noun}", None, href, kind, 0))
    return out


# short list of things this role should act on now; each item links to its record.
# Every kind keeps its top item and its "N more" row, so one flood cannot hide the rest
def attention_items(db: Session, role: Role, now: datetime | None = None) -> list[dict]:
    items = _per_kind(_all_items(db, role, _now(now)), role)
    tops, kinds = [], set()
    for i in items:
        if i["kind"] != "more" and i["kind"] not in kinds:
            kinds.add(i["kind"])
            tops.append(i)
    more = [i for i in items if i["kind"] == "more"]
    top_ids = {id(i) for i in tops}
    rest = [i for i in items if i["kind"] != "more" and id(i) not in top_ids]
    keep = {id(i) for i in (tops + more + rest)[:ATTENTION_LIMIT]}
    return [i for i in items if id(i) in keep]


# counts every item, not only the capped list, so "N things" is the real number
def briefing(db: Session, role: Role, now: datetime | None = None) -> dict:
    items = _all_items(db, role, _now(now))
    return {"role": role, "text": explainer.briefing_text(items), "items": len(items)}
