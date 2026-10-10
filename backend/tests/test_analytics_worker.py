import asyncio
import json

from app.core import events
from app.modules.analytics import worker


def test_only_breakdowns_and_qc_move_the_forecast():
    assert worker.moves_forecast({"topic": "machines", "type": "machine_event", "id": 1})
    assert worker.moves_forecast({"topic": "quality", "type": "roll", "id": 9})
    assert not worker.moves_forecast({"topic": "machines", "type": "crew", "id": 1})


def test_burst_of_breakdowns_tells_order_screens_to_refetch_once(monkeypatch):
    monkeypatch.setattr(worker, "DEBOUNCE_SECONDS", 0.05)
    monkeypatch.setattr(events, "_loop", None)

    async def run() -> list[dict]:
        events.bind_loop(asyncio.get_running_loop())
        seen = []

        async def watch_orders():
            async for chunk in events.stream(frozenset({"orders"})):
                if chunk.startswith("data: "):
                    seen.append(json.loads(chunk.removeprefix("data: ")))

        tasks = [
            asyncio.create_task(worker.forecast_listener()),
            asyncio.create_task(watch_orders()),
        ]
        await asyncio.sleep(0.01)  # both subscribed
        for _ in range(3):
            events.publish("machines", {"type": "machine_event", "id": 1})
        events.publish("machines", {"type": "crew", "id": 1})
        await asyncio.sleep(0.2)
        for task in tasks:
            task.cancel()
        return seen

    assert asyncio.run(run()) == [{"topic": "orders", "type": "forecast", "id": 0}]
