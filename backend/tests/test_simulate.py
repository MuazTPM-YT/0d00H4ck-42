import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory.models import YarnBatch
from app.modules.masters.models import Machine
from app.modules.orders.models import Order
from app.modules.production.models import MachineEvent, ProductionLog, WorkOrder
from app.modules.quality.models import QcCheck, Roll, RollBatch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import simulate  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


# row ids come from sequences that do not roll back, so compare by codes and values only
def fingerprint(db: Session) -> tuple:
    return (
        db.execute(select(Order.code, Order.qty_m, Order.status).order_by(Order.code)).all(),
        db.execute(
            select(Machine.code, MachineEvent.at, MachineEvent.status)
            .join(Machine, Machine.id == MachineEvent.machine_id)
            .order_by(MachineEvent.id)
        ).all(),
        db.execute(
            select(WorkOrder.code, ProductionLog.qty, ProductionLog.at)
            .join(WorkOrder, WorkOrder.id == ProductionLog.work_order_id)
            .order_by(ProductionLog.id)
        ).all(),
        db.execute(select(Roll.code, Roll.length_m, Roll.status).order_by(Roll.code)).all(),
        db.execute(
            select(Roll.code, YarnBatch.code, RollBatch.kg)
            .join(Roll, Roll.id == RollBatch.roll_id)
            .join(YarnBatch, YarnBatch.id == RollBatch.yarn_batch_id)
            .order_by(Roll.code, YarnBatch.code)
        ).all(),
        db.execute(
            select(Roll.code, QcCheck.decision, QcCheck.at)
            .join(Roll, Roll.id == QcCheck.roll_id)
            .order_by(QcCheck.id)
        ).all(),
    )


def run_in_rolled_back_transaction(engine) -> tuple:
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        simulate.simulate(db, NOW, days=2, seed=7)
        return fingerprint(db)
    finally:
        db.close()
        outer.rollback()
        conn.close()


def test_simulator_is_deterministic(engine):
    first = run_in_rolled_back_transaction(engine)
    second = run_in_rolled_back_transaction(engine)
    orders, events, logs, rolls, lineage, checks = first
    assert orders and events and logs and rolls and lineage and checks
    assert first == second
