from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role
from app.modules.dispatch import service
from app.modules.dispatch.models import DispatchStatus
from app.modules.dispatch.schemas import DispatchOut

router = APIRouter(
    prefix="/dispatch",
    tags=["dispatch"],
    dependencies=[Depends(require_roles(Role.dispatch, Role.accounts))],
)


@router.get("/dispatches", response_model=Paged[DispatchOut])
def list_dispatches(
    page: PageDep, status: DispatchStatus | None = None, db: Session = Depends(get_db)
):
    return service.list_dispatches(db, page, status)
