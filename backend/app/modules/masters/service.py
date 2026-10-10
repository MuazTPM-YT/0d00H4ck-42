from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import Base
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, paginate
from app.modules.auth.models import User
from app.modules.masters.models import FabricRecipe, FabricType, FabricTypeStage, Machine
from app.modules.orders.models import Order, OrderStatus
from app.modules.production.models import WorkOrder, WorkOrderStatus

# child lists saved with their parent and replaced whole on update
CHILDREN: dict[str, type[Base]] = {"stages": FabricTypeStage, "recipe": FabricRecipe}


def list_rows(
    db: Session,
    model: type[Base],
    page: Page,
    q: str | None = None,
    search: tuple[str, ...] = (),
    active: bool | None = None,
) -> dict:
    stmt = select(model)
    if q and search:
        stmt = stmt.where(or_(*[getattr(model, col).ilike(f"%{q}%") for col in search]))
    if active is not None and hasattr(model, "active"):
        stmt = stmt.where(model.active == active)
    order = model.code if hasattr(model, "code") else model.id
    return paginate(db, stmt.order_by(order), page)


def get_row(db: Session, model: type[Base], row_id: int) -> Base:
    row = db.get(model, row_id)
    if not row:
        raise NotFound(f"{model.__tablename__} {row_id} not found")
    return row


def _apply(db: Session, row: Base, data: dict) -> None:
    for key, value in data.items():
        if key in CHILDREN:
            # flush the delete first, else unique (fabric_type_id, seq) clashes with new rows
            getattr(row, key).clear()
            db.flush()
            setattr(row, key, [CHILDREN[key](**child) for child in value])
        else:
            setattr(row, key, value)


# a machine holding jobs keeps its type and stays active, else those jobs can never finish
def _machine_change(db: Session, row: Machine, data: dict) -> None:
    if row.active == data["active"] and row.type == data["type"]:
        return
    job = db.scalar(
        select(WorkOrder.code)
        .where(
            WorkOrder.machine_id == row.id,
            WorkOrder.status.in_(
                [WorkOrderStatus.queued, WorkOrderStatus.running, WorkOrderStatus.paused]
            ),
        )
        .limit(1)
    )
    if job:
        raise Conflict(
            f"{row.code} still has {job} on it. Finish or move its jobs first.",
            field="active" if row.active != data["active"] else "type",
            code="in_use",
        )


def _fabric_spec(width, gsm, loss, stages, recipe) -> tuple:
    return (
        Decimal(width),
        Decimal(gsm),
        Decimal(loss),
        sorted((s["seq"], s["stage"]) for s in stages),
        sorted((r["fibre"], r["count"], Decimal(r["share_pct"])) for r in recipe),
    )


# route, recipe and spec decide yarn needs and when rolls reach QC: frozen while orders are open
def _fabric_change(db: Session, row: FabricType, data: dict) -> None:
    now = _fabric_spec(
        row.width_cm,
        row.gsm,
        row.process_loss_pct,
        [{"seq": s.seq, "stage": s.stage} for s in row.stages],
        [{"fibre": r.fibre, "count": r.count, "share_pct": r.share_pct} for r in row.recipe],
    )
    new = _fabric_spec(
        data["width_cm"], data["gsm"], data["process_loss_pct"], data["stages"], data["recipe"]
    )
    if now == new:
        return
    open_order = db.scalar(
        select(Order.code)
        .where(Order.fabric_type_id == row.id, Order.status == OrderStatus.confirmed)
        .limit(1)
    )
    if open_order:
        raise Conflict(
            f"{open_order} is still being made from {row.code}. Route, recipe and size stay "
            "fixed until its open orders ship or are cancelled.",
            field="stages",
            code="in_use",
        )


GUARDS = {Machine: _machine_change, FabricType: _fabric_change}


def create_row(db: Session, user: User, model: type[Base], data: BaseModel) -> Base:
    row = model()
    _apply(db, row, data.model_dump())
    db.add(row)
    db.flush()
    audit.record(
        db, user.id, "create", model.__tablename__, row.id, data=data.model_dump(mode="json")
    )
    db.commit()
    return row


def update_row(db: Session, user: User, model: type[Base], row_id: int, data: BaseModel) -> Base:
    row = get_row(db, model, row_id)
    if guard := GUARDS.get(model):
        guard(db, row, data.model_dump())
    _apply(db, row, data.model_dump())
    audit.record(
        db, user.id, "update", model.__tablename__, row.id, data=data.model_dump(mode="json")
    )
    db.commit()
    db.refresh(row)
    return row
