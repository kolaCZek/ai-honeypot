"""Dashboard FastAPI app factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import redis.asyncio as redis_async
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from shared.config import Settings, load_config
from shared.db import init_db, make_engine, make_session_factory

from .routes import router

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _resolve_config_path() -> str:
    return os.environ.get("CONFIG_PATH", "/config/config.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Optional[Settings] = getattr(app.state, "settings", None)
    if settings is None:
        settings = load_config(_resolve_config_path())
        app.state.settings = settings
    if not hasattr(app.state, "config_path"):
        app.state.config_path = _resolve_config_path()
    if not hasattr(app.state, "session_factory"):
        app.state.engine = make_engine(settings.storage.sqlite_path)
        app.state.session_factory = make_session_factory(app.state.engine)
    if hasattr(app.state, "engine"):
        await init_db(app.state.engine)
    if not hasattr(app.state, "redis"):
        try:
            app.state.redis = redis_async.from_url(
                settings.storage.redis_url, decode_responses=True,
            )
        except Exception:
            app.state.redis = None
    yield


def create_app(*, settings: Optional[Settings] = None, session_factory=None,
               redis_client=None, config_path: Optional[str] = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)
    if settings is not None:
        app.state.settings = settings
    if session_factory is not None:
        app.state.session_factory = session_factory
    if redis_client is not None:
        app.state.redis = redis_client
    if config_path is not None:
        app.state.config_path = config_path
    app.state.templates = templates
    app.include_router(router)
    return app
