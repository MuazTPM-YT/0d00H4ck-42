from decimal import Decimal

from sqlalchemy import select

from app.core.audit import AuditLog
from app.modules.orders.models import Order
from app.modules.production.models import WorkOrder, WorkOrderStatus
from app.modules.production.service import create_work_orders


def test_one_waiting_work_order_per_route_stage(db, buyer, dyed_fabric):
    order = Order(
        code="SO-T2",
        buyer_id=buyer.id,
        fabric_type_id=dyed_fabric.id,
        colour="Maroon",
        qty_m=Decimal(500),
        rate_paise_per_m=24000,
        deadline="2026-12-01",
    )
    db.add(order)
    db.flush()

    wos = create_work_orders(db, order.id, None)
    db.flush()  # sessions run with autoflush off
    assert [(w.stage, w.seq, w.unit, w.status) for w in wos] == [
        ("weaving", 1, "m", WorkOrderStatus.waiting),
        ("dyeing", 2, "m", WorkOrderStatus.waiting),
    ]
    assert all(w.planned_qty == Decimal(500) and w.code.startswith("WO-") for w in wos)
    assert db.scalar(select(AuditLog).where(AuditLog.entity_type == "work_orders")) is not None

    again = create_work_orders(db, order.id, None)
    assert [w.id for w in again] == [w.id for w in wos]
    assert len(db.scalars(select(WorkOrder).where(WorkOrder.order_id == order.id)).all()) == 2
