from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.tracking import service
from app.modules.tracking.schemas import TrackOut

# public: no login, token is the only key
router = APIRouter(prefix="/track", tags=["tracking"])


@router.get("/{token}", response_model=TrackOut)
def track(token: str = Path(min_length=10, max_length=64), db: Session = Depends(get_db)):
    order = service.order_by_token(db, token)
    return service.order_stage(db, order.id)
