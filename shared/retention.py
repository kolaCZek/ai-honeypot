"""IP retention sweeper: LRU (max_ips) + TTL (ttl_days)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .models import IPUniverse


async def sweep_retention(session: AsyncSession, settings: Settings) -> int:
    """Delete IPs (cascading pages/edges/logs/credentials) per retention policy.

    Returns count of evicted IPs.
    """
    cfg = settings.honeypot.retention
    evicted: set[str] = set()

    # TTL: delete IPs whose last_seen older than cutoff.
    if cfg.ttl_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.ttl_days)
        rows = (await session.execute(
            select(IPUniverse.ip).where(IPUniverse.last_seen < cutoff)
        )).scalars().all()
        evicted.update(rows)

    # LRU: keep newest max_ips by last_seen; delete the rest.
    if cfg.max_ips is not None:
        ordered = (await session.execute(
            select(IPUniverse.ip).order_by(IPUniverse.last_seen.desc())
        )).scalars().all()
        if len(ordered) > cfg.max_ips:
            evicted.update(ordered[cfg.max_ips:])

    if not evicted:
        return 0

    # Cascade via FK ON DELETE CASCADE; ensure pragma on sqlite.
    await session.execute(delete(IPUniverse).where(IPUniverse.ip.in_(evicted)))
    await session.commit()
    return len(evicted)
