"""Shared pytest fixtures: in-memory db + fakeredis + app factory."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import fakeredis.aioredis
import pytest
import pytest_asyncio

from shared.config import Settings, LLMConfig, HoneypotConfig, DashboardConfig, BasicAuthConfig, StorageConfig, SlowdownConfig, RateLimitConfig
from shared.db import init_db, make_engine, make_session_factory
from shared.llm import LLMClient


class FakeLLM(LLMClient):
    """LLMClient that returns canned responses without HTTP."""

    def __init__(self, html: str = '<!doctype html><html><head><title>x</title></head><body><a href="/users">u</a></body></html>'):
        self.calls = 0
        self.html = html
        self.raise_next = False

    async def generate(self, prompt: str, *, system=None):
        self.calls += 1
        if self.raise_next:
            from shared.llm import LLMError
            raise LLMError("forced")
        return self.html, 10, 20

    async def aclose(self):
        pass


def _make_settings(tmpdir: Path) -> Settings:
    secret_file = tmpdir / "secret.key"
    secret_file.write_bytes(b"\x00" * 32)
    return Settings(
        llm=LLMConfig(endpoint="http://x", api_key="k", model="m"),
        honeypot=HoneypotConfig(
            slowdown=SlowdownConfig(enabled=False, min_s=0, max_s=0),
            rate_limit=RateLimitConfig(max_concurrent_per_ip=10, block_on_exceed=False),
            whitelist_ips=["testclient", "127.0.0.1"],
            bait_endpoints=["/.env", "/admin", "/login", "/wp-login.php"],
            secret_key_file=str(secret_file),
        ),
        dashboard=DashboardConfig(basic_auth=BasicAuthConfig(username="a", password="b")),
        storage=StorageConfig(sqlite_path=":memory:", redis_url="redis://localhost"),
        secret_key=b"\x00" * 32,
    )


@pytest_asyncio.fixture
async def settings(tmp_path):
    return _make_settings(tmp_path)


@pytest_asyncio.fixture
async def engine(settings):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return make_session_factory(engine)


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def fake_llm():
    return FakeLLM()


@pytest_asyncio.fixture
async def app(settings, session_factory, fake_redis, fake_llm):
    from honeypot.main import create_app
    a = create_app(settings=settings, session_factory=session_factory,
                   redis_client=fake_redis, llm=fake_llm)
    # Manually run lifespan because TestClient does it too; we don't want double-init.
    # Instead we'll rely on TestClient.
    return a


@pytest_asyncio.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        # lifespan
        async with _lifespan_ctx(app):
            yield c


from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan_ctx(app):
    # Use Starlette lifespan via TestClient-style manual trigger.
    async with app.router.lifespan_context(app):
        yield


@pytest_asyncio.fixture
async def dashboard_app(settings, session_factory):
    from dashboard.main import create_app
    return create_app(settings=settings, session_factory=session_factory)


@pytest_asyncio.fixture
async def dashboard_client(dashboard_app):
    from httpx import ASGITransport, AsyncClient, BasicAuth
    transport = ASGITransport(app=dashboard_app)
    async with AsyncClient(transport=transport, base_url="http://testserver",
                           auth=BasicAuth("a", "b")) as c:
        async with _lifespan_ctx(dashboard_app):
            yield c


@pytest_asyncio.fixture
async def dashboard_noauth_client(dashboard_app):
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=dashboard_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        async with _lifespan_ctx(dashboard_app):
            yield c


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Seed minimal data: 1 IP, 1 page, 1 request_log, 1 cred, 1 edge."""
    from datetime import datetime, timezone
    from shared.models import (
        CredentialAttempt, IPUniverse, LinkEdge, Page, RequestLog,
    )
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        ipu = IPUniverse(ip="1.2.3.4", ua="curl/8 bot", country="CZ",
                         request_count=1, token_count_in=100, token_count_out=200,
                         first_seen=now, last_seen=now)
        s.add(ipu)
        await s.flush()
        s.add(Page(ip="1.2.3.4", path="/admin", content_type="text/html",
                   body="<html></html>", tokens_in=100, tokens_out=200, generated_at=now))
        s.add(RequestLog(ip="1.2.3.4", method="GET", path="/admin", status=200,
                        ua="curl/8 bot", was_generated=True, was_bait=True, ts=now))
        s.add(LinkEdge(ip="1.2.3.4", from_path="/admin", to_path="/users", created_at=now))
        s.add(CredentialAttempt(ip="1.2.3.4", path="/admin",
                                username="root", password="toor", ts=now))
        await s.commit()
    return "1.2.3.4"
