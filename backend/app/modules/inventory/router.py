from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.pagination import Paged, PageDep
from app.modules.inventory import service
from app.modules.inventory.models import BatchStatus
from app.modules.inventory.schemas import BatchOut

router = APIRouter(
    prefix="/inventory", tags=["inventory"], dependencies=[Depends(get_current_user)]
)


@router.get("/batches", response_model=Paged[BatchOut])
def list_batches(page: PageDep, status: BatchStatus | None = None, db: Session = Depends(get_db)):
    return service.list_batches(db, page, status)
