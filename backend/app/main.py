import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import events
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.errors import Unprocessable, install_error_handlers
from app.modules.analytics.router import router as analytics
from app.modules.auth.router import router as auth
from app.modules.dispatch.router import router as dispatch
from app.modules.finance.router import router as finance
from app.modules.inventory.router import router as inventory
from app.modules.masters.router import router as masters
from app.modules.orders.router import router as orders
from app.modules.production.router import router as production
from app.modules.quality.router import router as quality
from app.modules.tracking.router import router as tracking
from app.modules.workforce.router import router as workforce


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()
    events.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="Everest Textile Mills",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/api/openapi.json",
)
install_error_handlers(app)

system = APIRouter(tags=["system"])


@system.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# live updates: one SSE connection per browser tab, filtered by topic
@system.get("/stream", dependencies=[Depends(get_current_user)])
async def stream(topics: str = Query(..., description="comma list, e.g. stock,machines")):
    wanted = frozenset(t.strip() for t in topics.split(",") if t.strip())
    if not wanted or wanted - events.TOPICS:
        raise Unprocessable(
            f"Topics must be from: {', '.join(sorted(events.TOPICS))}", field="topics"
        )
    return StreamingResponse(
        events.stream(wanted),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


for r in (
    system,
    auth,
    masters,
    inventory,
    orders,
    production,
    workforce,
    quality,
    tracking,
    dispatch,
    finance,
    analytics,
):
    app.include_router(r, prefix="/api")
