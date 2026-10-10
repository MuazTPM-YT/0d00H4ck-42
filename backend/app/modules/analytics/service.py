from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.modules.analytics import forecast
from app.modules.analytics.models import Insight, InsightStatus
from app.modules.auth.models import Role
from app.modules.orders.models import Order, OrderStatus

INSIGHT_TRANSITIONS = {
    InsightStatus.open: {InsightStatus.acknowledged, InsightStatus.resolved},
    InsightStatus.acknowledged: {InsightStatus.resolved},
}
RISK_ORDER = {"late": 0, "at_risk": 1, "on_track": 2}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def list_insights(db: Session, page: Page, status: InsightStatus | None = None) -> dict:
    stmt = select(Insight).order_by(Insight.id.desc())
    if status:
        stmt = stmt.where(Insight.status == status)
    return paginate(db, stmt, page)


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
