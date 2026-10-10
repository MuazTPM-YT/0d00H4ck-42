import asyncio
import json
import threading

from app.core import events


def test_publish_from_worker_thread_reaches_matching_subscriber_only():
    async def run():
        events.bind_loop(asyncio.get_running_loop())
        machines = events.stream(frozenset({"machines"}))
        stock = events.stream(frozenset({"stock"}))
        assert await anext(machines) == "retry: 3000\n\n"
        assert await anext(stock) == "retry: 3000\n\n"

        # services publish from FastAPI's threadpool, not the event loop
        t = threading.Thread(target=events.publish, args=("machines", {"type": "status", "id": 7}))
        t.start()
        t.join()

        message = await asyncio.wait_for(anext(machines), 1)
        assert json.loads(message.removeprefix("data: ")) == {
            "topic": "machines",
            "type": "status",
            "id": 7,
        }
        stock_next = asyncio.ensure_future(anext(stock))
        await asyncio.sleep(0.05)
        assert not stock_next.done()  # stock subscriber got nothing
        stock_next.cancel()
        await machines.aclose()

    asyncio.run(run())
