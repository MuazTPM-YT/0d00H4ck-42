from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.enums import Stage
from app.core.errors import NotFound
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import qty, yarn_kg_for_fabric
from app.modules.auth.models import User
from app.modules.inventory import service as inventory
from app.modules.masters.models import Buyer, FabricType
from app.modules.orders.models import Order, OrderStatus
from app.modules.production import service as production

ORDER_TRANSITIONS = {
    OrderStatus.draft: {OrderStatus.confirmed, OrderStatus.cancelled},
    OrderStatus.confirmed: {OrderStatus.cancelled, OrderStatus.closed},
}
# dyed fabrics are woven from undyed yarn
RAW_WHITE = "Raw White"


def list_orders(
    db: Session, page: Page, status: OrderStatus | None = None, q: str | None = None
) -> dict:
    stmt = select(Order).order_by(Order.id.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.join(Buyer, Buyer.id == Order.buyer_id).where(
            or_(Order.code.ilike(like), Buyer.name.ilike(like), Order.colour.ilike(like))
        )
    return paginate(db, stmt, page)


def get_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    return order


def _active_fabric(db: Session, fabric_type_id: int) -> FabricType:
    fabric = db.get(FabricType, fabric_type_id)
    if not fabric or not fabric.active:
        raise NotFound("Fabric type not found or inactive", field="fabric_type_id")
    return fabric


def create_order(db: Session, user: User, data) -> Order:
    buyer = db.get(Buyer, data.buyer_id)
    if not buyer or not buyer.active:
        raise NotFound("Buyer not found or inactive", field="buyer_id")
    _active_fabric(db, data.fabric_type_id)
    order = Order(code=next_code(db, "SO"), **data.model_dump())
    db.add(order)
    db.flush()
    audit.record(db, user.id, "create", "orders", order.id, data=data.model_dump(mode="json"))
    db.commit()
    events.publish("orders", {"type": "created", "id": order.id})
    return db.get(Order, order.id)


# live panel on the new-order form, before anything is saved
def requirement_preview(db: Session, data) -> list[dict]:
    fabric = _active_fabric(db, data.fabric_type_id)
    return requirement_lines(db, fabric, data.colour, data.qty_m)


# one transaction: confirm, plan work orders, reserve yarn. Any failure rolls all three back.
def confirm_order(db: Session, user: User, order_id: int) -> dict:
    locked = db.scalar(select(Order.id).where(Order.id == order_id).with_for_update())
    if locked is None:
        raise NotFound(f"Order {order_id} not found")
    order = db.get(Order, order_id, populate_existing=True)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.confirmed)
    order.status = OrderStatus.confirmed
    order.confirmed_at = datetime.now(UTC)
    db.flush()
    work_orders = production.create_work_orders(db, order.id, user.id)
    reserved = inventory.reserve(db, order.id, user.id)
    audit.record(
        db,
        user.id,
        "confirm",
        "orders",
        order.id,
        data={"work_orders": len(work_orders), "reservations": len(reserved)},
    )
    db.commit()
    events.publish("orders", {"type": "confirmed", "id": order.id})
    events.publish("stock", {"type": "reserved", "id": order.id})
    return inventory.order_allocation(db, order.id)


# retry after new yarn was approved (the to-buy list arrived)
def reserve_again(db: Session, user: User, order_id: int) -> dict:
    reserved = inventory.reserve(db, order_id, user.id)
    db.commit()
    if reserved:
        events.publish("orders", {"type": "reserved", "id": order_id})
        events.publish("stock", {"type": "reserved", "id": order_id})
    return inventory.order_allocation(db, order_id)


def cancel_order(db: Session, user: User, order_id: int, reason: str) -> Order:
    order = get_order(db, order_id)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.cancelled)
    order.status = OrderStatus.cancelled
    freed = inventory.release_order(db, order.id, user.id, f"Order cancelled: {reason}")
    audit.record(db, user.id, "cancel", "orders", order.id, reason=reason, data={"freed": freed})
    db.commit()
    events.publish("orders", {"type": "cancelled", "id": order.id})
    events.publish("stock", {"type": "released", "id": order.id})
    return order


# kg of each yarn the order needs, split by recipe share
def yarn_components(qty_m: Decimal, fabric: FabricType, order_colour: str) -> list[dict]:
    total = yarn_kg_for_fabric(qty_m, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
    dyed = any(s.stage == Stage.dyeing for s in fabric.stages)
    colour = RAW_WHITE if dyed else order_colour
    return [
        {
            "fibre": r.fibre,
            "count": r.count,
            "colour": colour,
            "kg_needed": qty(total * r.share_pct / 100),
        }
        for r in fabric.recipe
    ]


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# needed vs free yarn per component; free comes from inventory.free_stock
def yarn_requirement(db: Session, order_id: int) -> list[dict]:
    order = get_order(db, order_id)
    fabric = db.get(FabricType, order.fabric_type_id)
    return requirement_lines(db, fabric, order.colour, order.qty_m)


def requirement_lines(db: Session, fabric: FabricType, colour: str, qty_m: Decimal) -> list[dict]:
    lines = []
    for c in yarn_components(qty_m, fabric, colour):
        item = inventory.find_item(db, c["fibre"], c["count"], c["colour"])
        free = inventory.free_stock(db, item.id) if item else Decimal(0)
        lines.append({**c, "kg_free": qty(free), "kg_short": qty(max(c["kg_needed"] - free, 0))})
    return lines
