from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.modules.auth.models import Role, User
from app.modules.tracking import service
from app.modules.tracking.schemas import OrderView, TrackOut

router = APIRouter(prefix="/track", tags=["tracking"])

# office view of an order: sales talks to the buyer, accounts and dispatch look things up
Office = Depends(require_roles(Role.sales, Role.accounts, Role.dispatch))
Sales = Depends(require_roles(Role.sales))


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
