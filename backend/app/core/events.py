import asyncio
import json
from collections.abc import AsyncIterator

TOPICS = {"stock", "machines", "orders", "quality", "dispatch", "insights"}
HEARTBEAT_SECONDS = 15

# ponytail: in-process fan-out, one uvicorn worker. Multi-worker needs PG LISTEN/NOTIFY.
_subscribers: set[tuple[asyncio.Queue, frozenset[str]]] = set()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


# call after commit; safe from sync service code running in the threadpool
def publish(topic: str, payload: dict) -> None:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic}")
    if _loop is None:
        return
    message = json.dumps({"topic": topic, **payload}, default=str)
    for queue, topics in list(_subscribers):
        if topic in topics:
            _loop.call_soon_threadsafe(queue.put_nowait, message)


async def stream(topics: frozenset[str]) -> AsyncIterator[str]:
    queue: asyncio.Queue = asyncio.Queue()
    entry = (queue, topics)
    _subscribers.add(entry)
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                yield f"data: {message}\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        _subscribers.discard(entry)
