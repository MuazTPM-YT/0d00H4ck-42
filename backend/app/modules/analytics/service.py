from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, select, text
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.modules.analytics import detectors, explainer, forecast
from app.modules.analytics.models import Insight, InsightStatus, Severity
from app.modules.auth.models import Role, User
from app.modules.orders.models import Order, OrderStatus

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


# short list of things this role should act on now (low stock, late orders, QC queue...)
def attention_items(db: Session, role: Role) -> list[dict]:
    raise NotImplementedError("analytics.attention_items")
