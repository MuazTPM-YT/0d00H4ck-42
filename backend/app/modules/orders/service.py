from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Stage
from app.core.errors import NotFound
from app.core.pagination import Page, paginate
from app.core.units import qty, yarn_kg_for_fabric
from app.modules.inventory import service as inventory
from app.modules.masters.models import FabricType, YarnItem
from app.modules.orders.models import Order, OrderStatus

ORDER_TRANSITIONS = {
    OrderStatus.draft: {OrderStatus.confirmed, OrderStatus.cancelled},
    OrderStatus.confirmed: {OrderStatus.cancelled, OrderStatus.closed},
}
# dyed fabrics are woven from undyed yarn
RAW_WHITE = "Raw White"


def list_orders(db: Session, page: Page, status: OrderStatus | None = None) -> dict:
    stmt = select(Order).order_by(Order.id.desc())
    if status:
        stmt = stmt.where(Order.status == status)
    return paginate(db, stmt, page)


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
    order = db.get(Order, order_id)
    if not order:
        raise NotFound(f"Order {order_id} not found")
    fabric = db.get(FabricType, order.fabric_type_id)
    lines = []
    for c in yarn_components(order.qty_m, fabric, order.colour):
        item = db.scalar(
            select(YarnItem).where(
                YarnItem.fibre == c["fibre"],
                YarnItem.count == c["count"],
                YarnItem.colour == c["colour"],
            )
        )
        free = inventory.free_stock(db, item.id) if item else Decimal(0)
        lines.append({**c, "kg_free": qty(free), "kg_short": qty(max(c["kg_needed"] - free, 0))})
    return lines
