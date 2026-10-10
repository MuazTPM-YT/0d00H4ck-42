from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.codes import next_code
from app.core.enums import Stage
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.pagination import Page, paginate
from app.core.states import check_transition
from app.core.units import qty, yarn_kg_for_fabric
from app.modules.auth.models import User
from app.modules.dispatch.models import Dispatch, DispatchRoll, DispatchStatus
from app.modules.inventory import service as inventory
from app.modules.masters.models import Buyer, FabricType
from app.modules.orders.models import Order, OrderStatus
from app.modules.production import service as production
from app.modules.production.models import WorkOrder, WorkOrderStatus
from app.modules.quality.models import Roll

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
    _check_colour(db, order)
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


# yarn colour follows the order colour (no dyeing): every yarn must exist in masters, or the
# order can never reserve, issue or buy it
def _check_colour(db: Session, order: Order) -> None:
    fabric = db.get(FabricType, order.fabric_type_id)
    if _is_dyed(fabric):
        return
    for line in requirement_lines(db, fabric, order.colour, order.qty_m):
        if line["not_in_masters"]:
            raise Unprocessable(
                f"No yarn item {line['fibre']} {line['count']} {line['colour']} in masters. "
                "Pick a colour that exists for this fabric, or add the yarn item first.",
                field="colour",
            )


def _lock_order(db: Session, order_id: int) -> Order:
    locked = db.scalar(select(Order.id).where(Order.id == order_id).with_for_update())
    if locked is None:
        raise NotFound(f"Order {order_id} not found")
    return db.get(Order, order_id, populate_existing=True)


# metres on confirmed dispatches (read-only look at dispatch tables)
def shipped_m(db: Session, order_id: int) -> Decimal:
    metres = db.scalar(
        select(func.coalesce(func.sum(Roll.length_m), 0))
        .select_from(Dispatch)
        .join(DispatchRoll, DispatchRoll.dispatch_id == Dispatch.id)
        .join(Roll, Roll.id == DispatchRoll.roll_id)
        .where(Dispatch.order_id == order_id, Dispatch.status == DispatchStatus.confirmed)
    )
    return qty(metres)


# a truck still being filled or a machine still on the job: nothing can end the order yet
def _check_floor_idle(db: Session, order: Order) -> None:
    open_truck = db.scalar(
        select(Dispatch)
        .where(
            Dispatch.order_id == order.id,
            Dispatch.status.in_([DispatchStatus.draft, DispatchStatus.loading]),
        )
        .order_by(Dispatch.id)
        .limit(1)
    )
    if open_truck:
        raise Conflict(
            f"Dispatch {open_truck.code} for {order.code} is still {open_truck.status}. "
            "Confirm or empty it first",
            field="status",
        )
    busy = db.scalar(
        select(WorkOrder)
        .where(
            WorkOrder.order_id == order.id,
            WorkOrder.status.in_([WorkOrderStatus.running, WorkOrderStatus.paused]),
        )
        .order_by(WorkOrder.seq, WorkOrder.id)
        .limit(1)
    )
    if busy:
        raise Conflict(f"Finish or stop {busy.code} first", field="status", code="job_running")


def cancel_order(db: Session, user: User, order_id: int, reason: str) -> Order:
    order = _lock_order(db, order_id)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.cancelled)
    shipped = db.scalar(
        select(DispatchRoll.id)
        .join(Dispatch, Dispatch.id == DispatchRoll.dispatch_id)
        .where(Dispatch.order_id == order.id, Dispatch.status == DispatchStatus.confirmed)
        .limit(1)
    )
    if shipped:
        raise Conflict(
            f"Fabric of {order.code} has already shipped. Close the order instead", field="status"
        )
    _check_floor_idle(db, order)
    production.release_order_jobs(db, order.id, user.id)
    order.status = OrderStatus.cancelled
    freed = inventory.release_order(db, order.id, user.id, f"Order cancelled: {reason}")
    audit.record(db, user.id, "cancel", "orders", order.id, reason=reason, data={"freed": freed})
    db.flush()
    reserved = inventory.reserve_short_orders(db, user.id)
    db.commit()
    events.publish("orders", {"type": "cancelled", "id": order.id})
    events.publish("stock", {"type": "released", "id": order.id})
    inventory.publish_orders(r.order_id for r in reserved)
    return order


# confirmed -> closed: hand back the yarn still on hold. Never commits, so dispatch confirm can
# call it inside its own transaction (flush the dispatch as confirmed first)
def close_order(
    db: Session, order_id: int, user_id: int | None, reason: str | None = None
) -> Order:
    order = _lock_order(db, order_id)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.closed)
    _check_floor_idle(db, order)
    order.status = OrderStatus.closed
    freed = inventory.release_order(db, order.id, user_id, "order closed")
    audit.record(
        db,
        user_id,
        "close",
        "orders",
        order.id,
        reason=reason,
        data={"freed": freed, "shipped_m": str(shipped_m(db, order.id))},
    )
    db.flush()
    return order


# accounts closes by hand; closing short of the ordered metres needs a reason
def close(db: Session, user: User, order_id: int, reason: str | None) -> Order:
    order = get_order(db, order_id)
    check_transition(ORDER_TRANSITIONS, order.status, OrderStatus.closed)
    _check_floor_idle(db, order)
    reason = reason.strip() if reason else None
    if shipped_m(db, order.id) < order.qty_m and not reason:
        raise Unprocessable(
            f"{order.code} shipped less than its {qty(order.qty_m)} m. Say why it is closed short",
            field="reason",
        )
    close_order(db, order.id, user.id, reason)
    reserved = inventory.reserve_short_orders(db, user.id)
    db.commit()
    events.publish("orders", {"type": "closed", "id": order.id})
    events.publish("stock", {"type": "released", "id": order.id})
    inventory.publish_orders(r.order_id for r in reserved)
    return order


# kg of each yarn the order needs, split by recipe share; covers the floor's process allowance
def yarn_components(qty_m: Decimal, fabric: FabricType, order_colour: str) -> list[dict]:
    metres = qty_m * (1 + production.PROCESS_ALLOWANCE)
    total = yarn_kg_for_fabric(metres, fabric.width_cm, fabric.gsm, fabric.process_loss_pct)
    colour = RAW_WHITE if _is_dyed(fabric) else order_colour
    return [
        {
            "fibre": r.fibre,
            "count": r.count,
            "colour": colour,
            "kg_needed": qty(total * r.share_pct / 100),
        }
        for r in fabric.recipe
    ]


def _is_dyed(fabric: FabricType) -> bool:
    return any(s.stage == Stage.dyeing for s in fabric.stages)


# --- shared services (contract: docs/contracts.md). Never commit; caller owns the transaction.


# saved order: same short as the allocation (needed - reserved - issued), free shown beside it
def yarn_requirement(db: Session, order_id: int) -> list[dict]:
    get_order(db, order_id)
    return inventory.order_allocation(db, order_id)["lines"]


def requirement_lines(db: Session, fabric: FabricType, colour: str, qty_m: Decimal) -> list[dict]:
    lines = []
    for c in yarn_components(qty_m, fabric, colour):
        item = inventory.find_item(db, c["fibre"], c["count"], c["colour"])
        free = inventory.free_stock(db, item.id) if item else Decimal(0)
        lines.append(
            {
                **c,
                "yarn_item_id": item.id if item else None,
                "not_in_masters": item is None,
                "kg_free": qty(free),
                "kg_short": qty(max(c["kg_needed"] - free, 0)),
            }
        )
    return lines
