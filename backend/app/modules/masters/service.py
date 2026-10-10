from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.db import Base
from app.core.errors import NotFound
from app.core.pagination import Page, paginate
from app.modules.auth.models import User
from app.modules.masters.models import FabricRecipe, FabricTypeStage

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
    _apply(db, row, data.model_dump())
    audit.record(
        db, user.id, "update", model.__tablename__, row.id, data=data.model_dump(mode="json")
    )
    db.commit()
    db.refresh(row)
    return row
