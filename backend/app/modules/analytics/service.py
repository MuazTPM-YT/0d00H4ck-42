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
from app.modules.masters.models import Machine, YarnItem
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import MachineEvent, MachineStatus
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
    return paginate(db, stmt, page)


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
    if any(i.status == InsightStatus.resolved for i in same):
        return "skipped"
    live = same[0] if same else None
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


# all detectors over the ledger; safe to run from the loop and the button at the same time
def run_detectors(db: Session, now: datetime | None = None) -> dict:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": DETECTOR_LOCK})
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for finding in detectors.find_all(db, _now(now)):
        counts[upsert_insight(db, finding)] += 1
    db.commit()
    if counts["created"] or counts["updated"]:
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


# store: free yarn below the item's reorder level (waits for inventory.free_stock)
def _low_stock(db: Session, now: datetime) -> list[dict]:
    items = []
    for item in db.scalars(select(YarnItem).where(YarnItem.active, YarnItem.reorder_level_kg > 0)):
        try:
            free = inventory.free_stock(db, item.id)
        except NotImplementedError:
            return []
        if free < item.reorder_level_kg:
            name = f"{item.fibre} {item.count} {item.colour}"
            items.append(
                _item(
                    "low_stock",
                    Severity.critical if free <= 0 else Severity.warn,
                    f"{name} below reorder level",
                    f"{free} kg free, reorder at {item.reorder_level_kg} kg",
                    "/store/stock",
                    "yarn_items",
                    item.id,
                )
            )
    return items


# supervisor: machines stopped, or idle for more than half an hour
def _stopped_machines(db: Session, now: datetime) -> list[dict]:
    items = []
    for event, code in db.execute(
        select(MachineEvent, Machine.code)
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
        elif event.status == MachineStatus.idle and waited > IDLE_TOO_LONG:
            severity, title = Severity.warn, f"{code} idle"
        else:
            continue
        detail = _hours(waited) + (f": {event.reason}" if event.reason else "")
        machine_id = event.machine_id
        items.append(
            _item("machine", severity, title, detail, "/floor", "machines", machine_id, event.at)
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
            "/finance/invoices",
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
        for i in db.scalars(stmt.order_by(SEVERITY_RANK, Insight.id.desc()).limit(5))
    ]


ATTENTION_RULES = {
    Role.store: [_low_stock],
    Role.supervisor: [_stopped_machines],
    Role.qc: [_qc_waiting],
    Role.sales: [_orders_at_risk],
    Role.dispatch: [_shelf],
    Role.accounts: [_overdue],
    Role.owner: [_orders_at_risk, _overdue],
}
RANK = {Severity.critical: 0, Severity.warn: 1, Severity.info: 2}


# short list of things this role should act on now; each item links to its record
def attention_items(db: Session, role: Role, now: datetime | None = None) -> list[dict]:
    now = _now(now)
    items = [item for rule in ATTENTION_RULES[role] for item in rule(db, now)]
    items += _open_insights(db, role)
    items.sort(key=lambda i: (RANK[i["severity"]], i["since"] or now))
    return items[:ATTENTION_LIMIT]
