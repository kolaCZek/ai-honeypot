"""Honeypot FastAPI app factory + middleware wiring."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as redis_async
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config import Settings, load_config
from shared.db import init_db, make_engine, make_session_factory
from shared.llm import LLMClient
from shared.retention import sweep_retention

from .error_pages import nginx_429
from .rate_limit import IpConcurrentLimiter, TooManyRequests
from .routes import _client_ip, router as honeypot_router
from .slowdown import apply_slowdown


class HoneypotMiddleware(BaseHTTPMiddleware):
    """Slowdown + per-IP concurrent rate limit."""

    async def dispatch(self, request: Request, call_next):
        settings: Settings = request.app.state.settings
        rds = request.app.state.redis
        ip = _client_ip(request)
        cfg = settings.honeypot.rate_limit

        whitelist = settings.honeypot.whitelist_ips or []
        if ip in whitelist:
            return await call_next(request)

        try:
            async with IpConcurrentLimiter(
                rds, ip, cfg.max_concurrent_per_ip, cfg.block_on_exceed,
            ):
                await apply_slowdown(settings, ip)
                return await call_next(request)
        except TooManyRequests:
            body, headers, status = nginx_429()
            return Response(content=body, status_code=status, headers=headers)


async def _retention_loop(app: FastAPI):
    settings: Settings = app.state.settings
    factory = app.state.session_factory
    while True:
        try:
            async with factory() as s:
                await sweep_retention(s, settings)
        except Exception:
            pass
        await asyncio.sleep(300)


def _resolve_config_path() -> str:
    path = os.environ.get("CONFIG_PATH", "/config/config.yaml")
    return path


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Allow overrides set by tests before startup.
    settings: Optional[Settings] = getattr(app.state, "settings", None)
    if settings is None:
        settings = load_config(_resolve_config_path())
        app.state.settings = settings

    if not hasattr(app.state, "session_factory"):
        app.state.engine = make_engine(settings.storage.sqlite_path)
        app.state.session_factory = make_session_factory(app.state.engine)

    if hasattr(app.state, "engine"):
        await init_db(app.state.engine)

    if not hasattr(app.state, "redis"):
        app.state.redis = redis_async.from_url(
            settings.storage.redis_url, decode_responses=True,
        )

    if not hasattr(app.state, "llm"):
        app.state.llm = LLMClient(settings)

    sweeper = asyncio.create_task(_retention_loop(app))
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await app.state.llm.aclose()
        except Exception:
            pass


def create_app(*, settings: Optional[Settings] = None,
               session_factory=None, redis_client=None,
               llm: Optional[LLMClient] = None) -> FastAPI:
    """Build app. Overrides used by tests."""
    app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)

    if settings is not None:
        app.state.settings = settings
    if session_factory is not None:
        app.state.session_factory = session_factory
    if redis_client is not None:
        app.state.redis = redis_client
    if llm is not None:
        app.state.llm = llm

    app.add_middleware(HoneypotMiddleware)
    app.include_router(honeypot_router)
    return app


app = None  # populated by uvicorn entrypoint if needed
