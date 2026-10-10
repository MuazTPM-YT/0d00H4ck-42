from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.errors import Unprocessable
from app.modules.auth.models import Role, User
from app.modules.tracking import service
from app.modules.tracking.schemas import OrderView, StageRow, TrackOut

router = APIRouter(prefix="/track", tags=["tracking"])

# office view of an order: sales talks to the buyer, accounts and dispatch look things up
Office = Depends(require_roles(Role.accounts, Role.dispatch))
Sales = Depends(require_roles(Role.accounts))


# one call for a page of the order list: "ids=4,9,12", at most 100
@router.get("/stages", response_model=list[StageRow], dependencies=[Office])
def stages(ids: Annotated[str, Query(max_length=800)], db: Session = Depends(get_db)):
    try:
        order_ids = sorted({int(x) for x in ids.split(",") if x.strip()})
    except ValueError:
        raise Unprocessable("ids must be order ids split by commas", field="ids") from None
    if not order_ids or len(order_ids) > 100:
        raise Unprocessable("Send 1 to 100 order ids", field="ids")
    return service.stages(db, order_ids)


@router.get("/orders/{order_id}", response_model=OrderView, dependencies=[Office])
def order_view(order_id: int, db: Session = Depends(get_db)):
    return service.order_view(db, order_id)


@router.post("/orders/{order_id}/rotate-token", response_model=OrderView)
def rotate_token(order_id: int, db: Session = Depends(get_db), user: User = Sales):
    return service.rotate_token(db, user, order_id)


# public: no login, token is the only key; response_model strips anything not for buyers
@router.get("/{token}", response_model=TrackOut)
def track(token: str = Path(min_length=10, max_length=64), db: Session = Depends(get_db)):
    return service.public_view(db, token)
