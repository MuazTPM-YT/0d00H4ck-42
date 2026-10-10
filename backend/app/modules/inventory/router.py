from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.inventory import receiving, service
from app.modules.inventory import schemas as s
from app.modules.inventory.labels import qr_svg
from app.modules.inventory.models import BatchStatus, ExpectedDeliveryStatus, ReceiptStatus

router = APIRouter(
    prefix="/inventory", tags=["inventory"], dependencies=[Depends(get_current_user)]
)

Store = Depends(require_roles(Role.store))
Buyers = Depends(require_roles(Role.store, Role.accounts))  # people who order yarn from suppliers
OwnerOnly = Depends(require_roles())
Search = Annotated[str | None, Query(max_length=60)]


# --- stock (R2, R3)
@router.get("/stock", response_model=s.StockOut)
def stock(db: Session = Depends(get_db)):
    return service.stock_overview(db)


@router.get("/stock/warnings", response_model=list[s.StockRow])
def stock_warnings(db: Session = Depends(get_db)):
    return service.stock_warnings(db)


# --- batches
@router.get("/batches", response_model=Paged[s.BatchOut])
def list_batches(
    page: PageDep,
    status: BatchStatus | None = None,
    yarn_item_id: int | None = None,
    q: Search = None,
    db: Session = Depends(get_db),
):
    return service.list_batches(db, page, status, yarn_item_id, q)


@router.get("/batches/{batch_id}", response_model=s.BatchDetailOut)
def batch_detail(batch_id: int, db: Session = Depends(get_db)):
    return service.batch_detail(db, batch_id)


@router.post("/batches/{batch_id}/approve", response_model=s.BatchOut)
def approve(batch_id: int, db: Session = Depends(get_db), user: User = Store):
    return service.approve_batch(db, batch_id, user)


@router.post("/batches/{batch_id}/quarantine", response_model=s.BatchOut)
def quarantine(batch_id: int, data: s.ReasonIn, db: Session = Depends(get_db), user: User = Store):
    return service.quarantine_batch(db, batch_id, user, data.reason)


@router.post("/batches/{batch_id}/reject", response_model=s.BatchOut)
def reject(batch_id: int, data: s.ReasonIn, db: Session = Depends(get_db), user: User = Store):
    return service.reject_batch(db, batch_id, user, data.reason)


# owner only: quarantined yarn back into usable stock, with a reason on record
@router.post("/batches/{batch_id}/release", response_model=s.BatchOut)
def release(batch_id: int, data: s.ReasonIn, db: Session = Depends(get_db), user: User = OwnerOnly):
    return service.release_batch(db, batch_id, user, data.reason)


@router.post("/batches/{batch_id}/identify", response_model=s.BatchOut)
def identify(batch_id: int, data: s.IdentifyIn, db: Session = Depends(get_db), user: User = Store):
    return service.identify_batch(db, batch_id, user, data.yarn_item_id, data.supplier_lot)


# --- expected deliveries
@router.get("/expected-deliveries", response_model=Paged[s.ExpectedDeliveryOut])
def list_deliveries(
    page: PageDep,
    status: ExpectedDeliveryStatus | None = None,
    open_only: bool = False,
    db: Session = Depends(get_db),
):
    return receiving.list_deliveries(db, page, status, open_only)


@router.post("/expected-deliveries", response_model=s.ExpectedDeliveryOut, status_code=201)
def create_delivery(data: s.ExpectedDeliveryIn, db: Session = Depends(get_db), user: User = Buyers):
    return receiving.create_delivery(db, user, data)


@router.post("/expected-deliveries/{delivery_id}/cancel", response_model=s.ExpectedDeliveryOut)
def cancel_delivery(
    delivery_id: int, data: s.ReasonIn, db: Session = Depends(get_db), user: User = Buyers
):
    return receiving.cancel_delivery(db, user, delivery_id, data.reason)


# --- receiving
@router.get("/sample-labels", response_model=list[s.SampleLabel], dependencies=[Store])
def sample_labels(db: Session = Depends(get_db)):
    return receiving.sample_labels(db)


@router.post("/labels/check", response_model=s.LabelCheckOut, dependencies=[Store])
def check_label(data: s.LabelCheckIn, db: Session = Depends(get_db)):
    return receiving.check_label(db, data.payload, data.expected_delivery_id)


@router.get("/receipts", response_model=Paged[s.ReceiptOut])
def list_receipts(
    page: PageDep, status: ReceiptStatus | None = None, db: Session = Depends(get_db)
):
    return receiving.list_receipts(db, page, status)


@router.get("/receipts/{receipt_id}", response_model=s.ReceiptOut)
def get_receipt(receipt_id: int, db: Session = Depends(get_db)):
    return receiving.get_receipt(db, receipt_id)


@router.post("/receipts", response_model=s.ReceiptOut, status_code=201)
def create_receipt(data: s.ReceiptIn, db: Session = Depends(get_db), user: User = Store):
    return receiving.create_receipt(db, user, data)


@router.post("/receipts/{receipt_id}/lines", response_model=s.ReceiptLineOut)
def add_line(
    receipt_id: int, data: s.ReceiptLineIn, db: Session = Depends(get_db), user: User = Store
):
    return receiving.add_line(db, user, receipt_id, data)


@router.post("/receipts/{receipt_id}/confirm", response_model=s.ReceiptOut)
def confirm_receipt(receipt_id: int, db: Session = Depends(get_db), user: User = Store):
    return receiving.confirm_receipt(db, user, receipt_id)


# --- issue to production
@router.get(
    "/issue-plan",
    response_model=s.IssuePlanOut,
    dependencies=[Depends(require_roles(Role.store, Role.supervisor))],
)
def issue_plan(
    work_order: Annotated[str, Query(min_length=1, max_length=20)], db: Session = Depends(get_db)
):
    return service.issue_plan(db, work_order)


@router.post("/issues", response_model=s.StockMoveOut, status_code=201)
def issue(data: s.IssueIn, db: Session = Depends(get_db), user: User = Store):
    return service.issue(db, user, data)


@router.post("/returns", response_model=s.StockMoveOut, status_code=201)
def give_back(data: s.ReturnIn, db: Session = Depends(get_db), user: User = Store):
    return service.give_back(db, user, data)


# QR image for any label text (supplier sample labels, batch labels)
@router.get("/qr.svg")
def qr(data: Annotated[str, Query(min_length=1, max_length=300)]):
    return Response(
        qr_svg(data), media_type="image/svg+xml", headers={"Cache-Control": "max-age=3600"}
    )
