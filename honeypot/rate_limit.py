"""Per-IP concurrent request limiter backed by Redis (or fakeredis)."""
from __future__ import annotations

import asyncio
from typing import Optional


class TooManyRequests(Exception):
    pass


class IpConcurrentLimiter:
    """Async context manager: INCR ip:<ip>:inflight w/ 60s expiry.

    If block_on_exceed=True and count > max → raise TooManyRequests.
    Else wait (poll every 0.5s) until a slot frees.
    DECR on exit.
    """

    def __init__(self, redis, ip: str, max_concurrent: int, block_on_exceed: bool,
                 *, wait_timeout: float = 30.0, poll_interval: float = 0.5):
        self.redis = redis
        self.ip = ip
        self.max = max_concurrent
        self.block = block_on_exceed
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.key = f"ip:{ip}:inflight"
        self._acquired = False

    async def __aenter__(self):
        # First attempt
        count = await self.redis.incr(self.key)
        await self.redis.expire(self.key, 60)
        self._acquired = True

        if count <= self.max:
            return self

        # Over limit: either reject or wait.
        if self.block:
            await self.redis.decr(self.key)
            self._acquired = False
            raise TooManyRequests(f"too many concurrent requests for {self.ip}")

        # Wait: release our slot, poll, retry.
        await self.redis.decr(self.key)
        self._acquired = False
        waited = 0.0
        while waited < self.wait_timeout:
            await asyncio.sleep(self.poll_interval)
            waited += self.poll_interval
            cur = int(await self.redis.get(self.key) or 0)
            if cur < self.max:
                count = await self.redis.incr(self.key)
                await self.redis.expire(self.key, 60)
                self._acquired = True
                if count <= self.max:
                    return self
                await self.redis.decr(self.key)
                self._acquired = False
        raise TooManyRequests(f"timed out waiting for slot for {self.ip}")

    async def __aexit__(self, exc_type, exc, tb):
        if self._acquired:
            try:
                await self.redis.decr(self.key)
            except Exception:
                pass
            self._acquired = False
        return False
