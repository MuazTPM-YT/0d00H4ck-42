from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role
from app.modules.finance import service
from app.modules.finance.models import InvoiceStatus
from app.modules.finance.schemas import InvoiceOut

router = APIRouter(
    prefix="/finance", tags=["finance"], dependencies=[Depends(require_roles(Role.accounts))]
)


@router.get("/invoices", response_model=Paged[InvoiceOut])
def list_invoices(
    page: PageDep, status: InvoiceStatus | None = None, db: Session = Depends(get_db)
):
    return service.list_invoices(db, page, status)
