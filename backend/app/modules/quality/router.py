from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.pagination import Paged, PageDep
from app.modules.quality import service
from app.modules.quality.models import RollStatus
from app.modules.quality.schemas import RollOut

router = APIRouter(prefix="/quality", tags=["quality"], dependencies=[Depends(get_current_user)])


@router.get("/rolls", response_model=Paged[RollOut])
def list_rolls(
    page: PageDep,
    status: RollStatus | None = None,
    order_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_rolls(db, page, status, order_id)
