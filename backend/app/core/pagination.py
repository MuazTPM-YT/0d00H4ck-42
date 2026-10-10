from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class Page(BaseModel):
    limit: int
    offset: int


T = TypeVar("T")


class Paged(BaseModel, Generic[T]):
    items: list[T]
    total: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


PageDep = Annotated[Page, Depends(page_params)]


def paginate(db: Session, stmt: Select, page: Page) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = db.scalars(stmt.limit(page.limit).offset(page.offset)).all()
    return {"items": items, "total": total}
