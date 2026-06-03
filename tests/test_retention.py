from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from shared.config import (
    BasicAuthConfig,
    DashboardConfig,
    HoneypotConfig,
    LLMConfig,
    RetentionConfig,
    Settings,
    StorageConfig,
)
from shared.db import init_db, make_engine, make_session_factory
from shared.models import IPUniverse, Page
from shared.retention import sweep_retention


def _settings(max_ips=None, ttl_days=None) -> Settings:
    return Settings(
        llm=LLMConfig(endpoint="http://x", api_key="k", model="m"),
        honeypot=HoneypotConfig(retention=RetentionConfig(max_ips=max_ips, ttl_days=ttl_days)),
        dashboard=DashboardConfig(basic_auth=BasicAuthConfig(username="a", password="b")),
        storage=StorageConfig(sqlite_path=":memory:"),
    )


@pytest.fixture
async def session_factory():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await init_db(engine)
    sf = make_session_factory(engine)
    # Ensure FK cascade on every connection.
    async with engine.begin() as c:
        await c.exec_driver_sql("PRAGMA foreign_keys=ON")
    yield sf
    await engine.dispose()


async def test_lru_evicts_oldest(session_factory):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with session_factory() as s:
        for i in range(25):
            ip = f"10.0.0.{i}"
            s.add(IPUniverse(ip=ip, first_seen=base, last_seen=base + timedelta(minutes=i)))
            s.add(Page(ip=ip, path="/", content_type="text/html", body="x"))
        await s.commit()

    async with session_factory() as s:
        from sqlalchemy import text
        await s.execute(text("PRAGMA foreign_keys=ON"))
        n = await sweep_retention(s, _settings(max_ips=20))
        assert n == 5

    async with session_factory() as s:
        remaining = (await s.execute(select(IPUniverse.ip))).scalars().all()
        assert len(remaining) == 20
        # Oldest 5 (i=0..4) gone.
        for i in range(5):
            assert f"10.0.0.{i}" not in remaining
        # Their pages also gone (cascade).
        pages = (await s.execute(select(Page))).scalars().all()
        assert len(pages) == 20


async def test_disabled_is_noop(session_factory):
    async with session_factory() as s:
        for i in range(3):
            s.add(IPUniverse(ip=f"2.0.0.{i}"))
        await s.commit()
        n = await sweep_retention(s, _settings())
        assert n == 0
