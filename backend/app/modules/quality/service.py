from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import Page, paginate
from app.modules.quality.models import Roll, RollStatus

ROLL_TRANSITIONS = {
    RollStatus.in_process: {RollStatus.awaiting_qc},
    RollStatus.awaiting_qc: {RollStatus.passed, RollStatus.rework, RollStatus.rejected},
    RollStatus.rework: {RollStatus.awaiting_qc, RollStatus.rejected},
    RollStatus.passed: {RollStatus.dispatched},
}


def list_rolls(
    db: Session, page: Page, status: RollStatus | None = None, order_id: int | None = None
) -> dict:
    stmt = select(Roll).order_by(Roll.id.desc())
    if status:
        stmt = stmt.where(Roll.status == status)
    if order_id:
        stmt = stmt.where(Roll.order_id == order_id)
    return paginate(db, stmt, page)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# full genealogy: order, loom, shift, weaver, yarn batches + suppliers, qc attempts, events
def roll_trace(db: Session, roll_id: int) -> dict:
    raise NotImplementedError("quality.roll_trace")
