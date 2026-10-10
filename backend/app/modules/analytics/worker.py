import asyncio
import json
import logging
from contextlib import asynccontextmanager

from app.core import events
from app.core.db import SessionLocal
from app.modules.analytics import service

log = logging.getLogger(__name__)

FIRST_RUN_SECONDS = 10  # let the server finish starting first
INTERVAL_SECONDS = 300
DEBOUNCE_SECONDS = 5.0  # a burst of floor events causes one refresh, not twenty


def _run_detectors() -> None:
    with SessionLocal() as db:
        service.run_detectors(db)


async def detector_loop() -> None:
    await asyncio.sleep(FIRST_RUN_SECONDS)
    while True:
        try:
            await asyncio.to_thread(_run_detectors)
        except Exception:
            log.exception("detector run failed")
        await asyncio.sleep(INTERVAL_SECONDS)


# a breakdown or a QC decision moves delivery dates
def moves_forecast(message: dict) -> bool:
    return message["topic"] == "quality" or message.get("type") == "machine_event"


# forecasts are computed on read, so "recompute" means: tell every open delivery view to refetch
async def forecast_listener() -> None:
    pending: asyncio.Task | None = None

    async def announce() -> None:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        events.publish("orders", {"type": "forecast", "id": 0})

    async for chunk in events.stream(frozenset({"machines", "quality"})):
        if not chunk.startswith("data: "):
            continue
        if moves_forecast(json.loads(chunk.removeprefix("data: "))) and (
            pending is None or pending.done()
        ):
            pending = asyncio.create_task(announce())


# started by the analytics router; FastAPI merges router lifespans into the app's
@asynccontextmanager
async def lifespan(_):
    tasks = [asyncio.create_task(detector_loop()), asyncio.create_task(forecast_listener())]
    yield
    for task in tasks:
        task.cancel()
