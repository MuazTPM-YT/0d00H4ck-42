from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.pagination import Paged, PageDep
from app.modules.auth.models import Role, User
from app.modules.finance import closing, service
from app.modules.finance.models import InvoiceStatus, WageRunStatus
from app.modules.finance.schemas import (
    ExpenseIn,
    ExpenseOut,
    InvoiceDetail,
    InvoiceRow,
    MachineProduction,
    Month,
    MonthCloseIn,
    MonthRecord,
    MonthView,
    OrderCost,
    OrderCostRow,
    PaymentIn,
    PaymentOut,
    PaymentRow,
    ReopenIn,
    WageRunDetail,
    WageRunIn,
    WageRunOut,
)

# the books are for accounts; owner passes every role check
Accounts = Depends(require_roles(Role.accounts))
router = APIRouter(prefix="/finance", tags=["finance"], dependencies=[Accounts])


@router.get("/invoices", response_model=Paged[InvoiceRow])
def list_invoices(
    page: PageDep,
    status: InvoiceStatus | None = None,
    outstanding: bool = False,
    buyer_id: int | None = None,
    order_id: int | None = None,
    db: Session = Depends(get_db),
):
    return service.list_invoices(db, page, status, outstanding, buyer_id, order_id)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return service.get_invoice(db, invoice_id)


@router.get("/payments", response_model=Paged[PaymentRow])
def list_payments(page: PageDep, invoice_id: int | None = None, db: Session = Depends(get_db)):
    return service.list_payments(db, page, invoice_id)


@router.post("/payments", response_model=PaymentOut, status_code=201)
def record_payment(data: PaymentIn, db: Session = Depends(get_db), user: User = Accounts):
    return service.record_payment(db, user, data)


@router.get("/wage-runs", response_model=Paged[WageRunOut])
def list_wage_runs(page: PageDep, db: Session = Depends(get_db)):
    return service.list_wage_runs(db, page)


@router.post("/wage-runs", response_model=WageRunDetail, status_code=201)
def create_wage_run(data: WageRunIn, db: Session = Depends(get_db), user: User = Accounts):
    return service.create_wage_run(db, user, data.period_start, data.period_end)


@router.get("/wage-runs/{run_id}", response_model=WageRunDetail)
def get_wage_run(run_id: int, db: Session = Depends(get_db)):
    return service.wage_run_detail(db, run_id)


@router.post("/wage-runs/{run_id}/recompute", response_model=WageRunDetail)
def recompute_wage_run(run_id: int, db: Session = Depends(get_db), user: User = Accounts):
    return service.recompute_wage_run(db, user, run_id)


@router.delete("/wage-runs/{run_id}", status_code=204)
def delete_wage_run(run_id: int, db: Session = Depends(get_db), user: User = Accounts):
    service.delete_wage_run(db, user, run_id)


@router.post("/wage-runs/{run_id}/finalize", response_model=WageRunDetail)
def finalize_wage_run(run_id: int, db: Session = Depends(get_db), user: User = Accounts):
    return service.set_wage_run_status(db, user, run_id, WageRunStatus.final)


@router.post("/wage-runs/{run_id}/pay", response_model=WageRunDetail)
def pay_wage_run(run_id: int, db: Session = Depends(get_db), user: User = Accounts):
    return service.set_wage_run_status(db, user, run_id, WageRunStatus.paid)


@router.get("/expenses", response_model=Paged[ExpenseOut])
def list_expenses(page: PageDep, month: Month | None = None, db: Session = Depends(get_db)):
    return service.list_expenses(db, page, month)


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def create_expense(data: ExpenseIn, db: Session = Depends(get_db), user: User = Accounts):
    return service.create_expense(db, user, data)


@router.get("/orders/{order_id}/cost", response_model=OrderCost)
def order_cost(order_id: int, db: Session = Depends(get_db)):
    return service.order_cost(db, order_id)


# orders worked or billed in the month, each with its cost to date
@router.get("/order-costs", response_model=list[OrderCostRow])
def order_costs(month: Month, db: Session = Depends(get_db)):
    return service.order_costs(db, month)


@router.get("/machine-production", response_model=list[MachineProduction])
def machine_production(month: Month, db: Session = Depends(get_db)):
    return service.machine_production(db, month)


@router.get("/month", response_model=MonthView)
def month_view(month: Month, db: Session = Depends(get_db)):
    return service.month_view(db, month)


@router.get("/month/records", response_model=list[MonthRecord])
def month_records(
    month: Month,
    kind: Literal["invoiced", "received", "yarn_bills", "wages", "wages_paid", "expenses"],
    db: Session = Depends(get_db),
):
    return service.month_records(db, month, kind)


@router.get("/month-closes", response_model=list[str])
def month_closes(db: Session = Depends(get_db)):
    return closing.closed_months(db)


@router.post("/month-closes", response_model=list[str], status_code=201)
def close_month(data: MonthCloseIn, db: Session = Depends(get_db), user: User = Accounts):
    return closing.close_month(db, user, data.month)


# reopening changes closed books: owner only, with a reason
@router.post("/month-closes/{month}/reopen", response_model=list[str])
def reopen_month(
    month: Month,
    data: ReopenIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles()),
):
    return closing.reopen_month(db, user, month, data.reason)
