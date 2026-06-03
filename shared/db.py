"""Async SQLAlchemy engine factory + init_db."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


def make_engine(sqlite_path: str, *, echo: bool = False) -> AsyncEngine:
    """Build async engine from a sqlite path or a full async URL."""
    if "://" in sqlite_path:
        url = sqlite_path
    else:
        url = f"sqlite+aiosqlite:///{sqlite_path}"
    return create_async_engine(url, echo=echo, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables; safe to call repeatedly."""
    async with engine.begin() as conn:
        # Enable FK cascades on sqlite.
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
