"""FastAPI 依赖：认证上下文、数据库会话/工厂、本地合成数据适配器。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.security import ShopContext, get_auth_context
from ..db import get_session, get_sessionmaker
from ..integrations.local.adapter import LocalDataAdapter


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


def get_local_data(request: Request) -> LocalDataAdapter:
    data = getattr(request.app.state, "local_data", None)
    if data is None:
        raise HTTPException(status_code=503, detail={
            "code": "data_unavailable", "message": "数据服务暂不可用，请稍后重试或联系管理员"})
    return data


__all__ = ["ShopContext", "get_auth_context", "get_session", "get_session_factory",
           "get_local_data", "AsyncIterator"]
