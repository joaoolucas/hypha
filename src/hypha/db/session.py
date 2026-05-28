"""Lazy async engine/session. No-ops gracefully when DATABASE_URL is unset (MVP)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings
from .models import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure() -> async_sessionmaker[AsyncSession] | None:
    global _engine, _sessionmaker
    url = get_settings().database_url
    if not url:
        return None
    if _sessionmaker is None:
        _engine = create_async_engine(url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_models() -> None:
    if _ensure() is None:
        return
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def session() -> AsyncSession | None:
    sm = _ensure()
    return sm() if sm else None
