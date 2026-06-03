"""Cross-process hot-reload coordination via Redis pub/sub.

Publisher (dashboard) calls `publish_reload(redis)` after saving config.
Subscriber (honeypot) runs `subscribe_reload(redis, on_reload)` as a
background asyncio task; on every message it invokes `on_reload()`
which is responsible for reloading settings and rebuilding dependent
clients (LLMClient, etc.).
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .config import RELOAD_CHANNEL


async def publish_reload(redis_client) -> int:
    """Publish a reload notification. Returns the number of subscribers reached."""
    return await redis_client.publish(RELOAD_CHANNEL, "reload")


async def subscribe_reload(
    redis_client,
    on_reload: Callable[[], Awaitable[None]],
) -> None:
    """Long-running subscriber: invokes on_reload() on every message.

    Designed to be spawned via `asyncio.create_task`. Cancellation safe:
    closes the pubsub on exit and swallows CancelledError.
    """
    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(RELOAD_CHANNEL)
        async for msg in pubsub.listen():
            if msg is None:
                continue
            if msg.get("type") != "message":
                continue
            try:
                await on_reload()
            except Exception:
                # Best-effort: never let a bad config crash the subscriber.
                pass
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await pubsub.unsubscribe(RELOAD_CHANNEL)
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass
