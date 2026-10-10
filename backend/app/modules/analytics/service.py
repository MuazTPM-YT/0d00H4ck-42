from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import Page, paginate
from app.modules.analytics.models import Insight, InsightStatus
from app.modules.auth.models import Role

INSIGHT_TRANSITIONS = {
    InsightStatus.open: {InsightStatus.acknowledged, InsightStatus.resolved},
    InsightStatus.acknowledged: {InsightStatus.resolved},
}


def list_insights(db: Session, page: Page, status: InsightStatus | None = None) -> dict:
    stmt = select(Insight).order_by(Insight.id.desc())
    if status:
        stmt = stmt.where(Insight.status == status)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# projected finish = remaining metres / recent throughput + QC lag; on_track | at_risk | late
def delivery_estimate(db: Session, order_id: int) -> dict:
    raise NotImplementedError("analytics.delivery_estimate")


# short list of things this role should act on now (low stock, late orders, QC queue...)
def attention_items(db: Session, role: Role) -> list[dict]:
    raise NotImplementedError("analytics.attention_items")
