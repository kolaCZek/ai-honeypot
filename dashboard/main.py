"""Dashboard FastAPI app factory."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

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
    if not hasattr(app.state, "session_factory"):
        app.state.engine = make_engine(settings.storage.sqlite_path)
        app.state.session_factory = make_session_factory(app.state.engine)
    if hasattr(app.state, "engine"):
        await init_db(app.state.engine)
    yield


def create_app(*, settings: Optional[Settings] = None, session_factory=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)
    if settings is not None:
        app.state.settings = settings
    if session_factory is not None:
        app.state.session_factory = session_factory
    app.state.templates = templates
    app.include_router(router)
    return app
