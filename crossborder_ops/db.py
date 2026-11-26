"""数据库基础设施：async engine / sessionmaker / 会话依赖。

生产环境用 Alembic 迁移；`auto_create_tables=True` 只为 dev/test 提供
"空库直接跑"的便利，不能替代迁移。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import get_settings
from .models.base import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        if url.startswith("sqlite"):
            # 测试/本地：NullPool 避免连接跨事件循环复用；WAL 支持并发读写
            _engine = create_async_engine(url, poolclass=NullPool,
                                          connect_args={"timeout": 30})

            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_pragma(dbapi_connection, _record):  # pragma: no cover
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        else:
            _engine = create_async_engine(url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def init_models() -> None:
    """仅 dev/test：按 metadata 建表（生产走 alembic upgrade head）。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
