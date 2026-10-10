from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import Base, get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import User
from app.modules.masters import models as m
from app.modules.masters import schemas as s
from app.modules.masters import service

router = APIRouter(prefix="/masters", tags=["masters"])

Search = Annotated[str | None, Query(max_length=100)]
OwnerOnly = Depends(require_roles())


# same four routes for every master: list, get, create, update (full replace)
def crud(
    path: str,
    model: type[Base],
    body: type[BaseModel],
    out: type[BaseModel],
    search: tuple[str, ...],
) -> None:
    @router.get(f"/{path}", response_model=Paged[out], name=f"list_{path}")
    def list_(
        page: PageDep,
        q: Search = None,
        active: bool | None = None,
        db: Session = Depends(get_db),
        _: User = Depends(get_current_user),
    ):
        return service.list_rows(db, model, page, q, search, active)

    @router.get(f"/{path}/{{row_id}}", response_model=out, name=f"get_{path}")
    def get(row_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
        return service.get_row(db, model, row_id)

    @router.post(f"/{path}", response_model=out, status_code=201, name=f"create_{path}")
    def create(data: body, db: Session = Depends(get_db), user: User = OwnerOnly):
        return service.create_row(db, user, model, data)

    @router.put(f"/{path}/{{row_id}}", response_model=out, name=f"update_{path}")
    def update(row_id: int, data: body, db: Session = Depends(get_db), user: User = OwnerOnly):
        return service.update_row(db, user, model, row_id, data)


crud("suppliers", m.Supplier, s.SupplierIn, s.SupplierOut, ("code", "name", "city"))
crud("buyers", m.Buyer, s.BuyerIn, s.BuyerOut, ("code", "name", "city", "gstin"))
crud("yarn-items", m.YarnItem, s.YarnItemIn, s.YarnItemOut, ("fibre", "count", "colour"))
crud("fabric-types", m.FabricType, s.FabricTypeIn, s.FabricTypeOut, ("code", "name"))
crud("machines", m.Machine, s.MachineIn, s.MachineOut, ("code", "name", "type"))
crud("workers", m.Worker, s.WorkerIn, s.WorkerOut, ("code", "name"))
crud("shifts", m.Shift, s.ShiftIn, s.ShiftOut, ("code", "name"))


@router.get("/locations", response_model=Paged[s.LocationOut])
def list_locations(
    page: PageDep, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    return service.list_rows(db, m.Location, page)
