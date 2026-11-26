"""审计写入：成功路径与业务同事务；失败路径用独立事务，确保失败也留痕。

敏感信息脱敏：
- 命中敏感键名的字段统一写 "***"；
- 长随机串（疑似 token）做掩码；
- 永不记录 Authorization / Cookie / 密钥类原文。
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "app_secret", "client_secret",
    "secret", "password", "passwd", "authorization", "cookie", "api_key", "key",
}
TOKEN_PATTERN = re.compile(r"^(EA[A-Za-z0-9_-]{20,}|[A-Fa-f0-9]{32,})$")


def _jsonable(value: Any) -> Any:
    """审计落 JSON 前把 Decimal/日期转成字符串（避免序列化失败导致业务回滚）。"""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def mask_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if str(k).lower() in SENSITIVE_KEYS else mask_value(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(v) for v in value]
    if isinstance(value, str) and TOKEN_PATTERN.match(value):
        return "***"
    return value


async def record(session: AsyncSession, *, shop_id: str, actor: str, role: str,
                 action: str, entity_type: str, entity_id: str,
                 before: dict | None = None, after: dict | None = None,
                 request_id: str | None = None, operation_id: str | None = None,
                 result: str = "ok", failure_reason: str | None = None) -> AuditLog:
    """同事务写入；调用方负责 commit（与业务变更保持原子性）。"""
    entry = AuditLog(
        shop_id=shop_id, actor_id=actor, actor_role=role, action=action,
        entity_type=entity_type, entity_id=entity_id,
        before_data=_jsonable(mask_value(before)) if before is not None else None,
        after_data=_jsonable(mask_value(after)) if after is not None else None,
        request_id=request_id, operation_id=operation_id,
        result=result, failure_reason=(failure_reason or "")[:2000] or None,
    )
    session.add(entry)
    await session.flush()
    return entry


async def record_failure(session_factory, *, shop_id: str, actor: str, role: str,
                         action: str, entity_type: str, entity_id: str,
                         before: dict | None = None, after: dict | None = None,
                         request_id: str | None = None, reason: str = "") -> None:
    """独立事务记录失败，避免被业务回滚带走；审计失败只记日志，不掩盖原始错误。"""
    try:
        async with session_factory() as session:
            async with session.begin():
                await record(session, shop_id=shop_id, actor=actor, role=role,
                             action=action, entity_type=entity_type, entity_id=entity_id,
                             before=before, after=after, request_id=request_id,
                             result="failed", failure_reason=reason)
    except Exception:  # noqa: BLE001 - 审计失败不能覆盖原始业务异常
        logger.exception("失败审计写入异常")


async def record_failure_for_request(session_factory, *, ctx, request_id, action: str,
                                     entity_type: str, entity_id: str,
                                     exc: BaseException,
                                     before: dict | None = None) -> None:
    """路由捕获到异常时调用：用独立事务写失败审计，不掩盖原始异常。"""
    await record_failure(
        session_factory, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action=action, entity_type=entity_type, entity_id=entity_id,
        before=before, after=None, request_id=request_id,
        reason=f"{type(exc).__name__}: {exc}"[:500])
