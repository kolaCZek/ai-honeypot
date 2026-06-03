"""Random slowdown applied to non-whitelisted IPs."""
from __future__ import annotations

import asyncio
import random

from shared.config import Settings


async def apply_slowdown(settings: Settings, ip: str) -> float:
    """Sleep random.uniform(min,max) seconds if enabled & not whitelisted.

    Returns the actual seconds slept (0 if skipped).
    """
    cfg = settings.honeypot.slowdown
    if not cfg.enabled:
        return 0.0
    if ip in (settings.honeypot.whitelist_ips or []):
        return 0.0
    secs = random.uniform(cfg.min_s, cfg.max_s)
    await asyncio.sleep(secs)
    return secs
