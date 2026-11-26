# -*- coding: utf-8 -*-
"""pytest 全局夹具：所有测试默认跑 SQLite（CI 可切 PG），不需要真实 Meta/Amazon 凭证。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 必须在导入 crossborder_ops 之前设置环境变量（settings 是惰性单例）
_TMP = Path(tempfile.mkdtemp(prefix="crossborder-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["APP_ENV"] = "dev"
os.environ.pop("API_TOKENS", None)
os.environ.pop("WEBHOOK_ALLOWED_SHOPS", None)
os.environ["DEFAULT_API_TOKEN"] = "dev-token"
os.environ.setdefault("DEFAULT_SHOP_ID", "S1")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest_asyncio.fixture
async def api(sessionmaker_):
    """ASGI 直连客户端（不跑 lifespan，避免跨事件循环共享 engine）。"""
    import httpx

    from crossborder_ops.integrations.local.adapter import LocalDataAdapter
    from crossborder_ops.main import app

    app.state.local_data = LocalDataAdapter()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def sessionmaker_():
    from crossborder_ops.db import get_sessionmaker, init_models

    await init_models()
    from crossborder_ops.repositories import business as repo

    async with get_sessionmaker()() as session:
        async with session.begin():
            for shop_id in ("S1", "S2"):
                if await repo.get_shop(session, shop_id) is None:
                    await repo.create_shop(session, id=shop_id, name=f"shop-{shop_id}")
    return get_sessionmaker()


@pytest_asyncio.fixture
async def redis_client():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest.fixture
def two_shops(monkeypatch):
    """两个店铺的 token 映射；用于验证 shop 隔离。"""
    import json

    from crossborder_ops.config import get_settings

    monkeypatch.setenv("API_TOKENS", json.dumps({
        "tok_s1": {"shop_id": "S1", "actor": "ops_s1", "role": "admin"},
        "tok_s2": {"shop_id": "S2", "actor": "ops_s2", "role": "admin"},
        "tok_viewer": {"shop_id": "S1", "actor": "viewer", "role": "viewer"},
    }))
    get_settings.cache_clear()
    try:
        yield {"S1": "tok_s1", "S2": "tok_s2", "viewer": "tok_viewer"}
    finally:
        get_settings.cache_clear()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
