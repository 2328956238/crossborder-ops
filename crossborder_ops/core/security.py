"""认证与租户上下文。

安全原则：
1. shop_id 只能由后端 token 映射出来，客户端请求体不得指定；
2. 无 token → 401；token 不在映射表 → 401（fail-closed，不做"没配置就放行"）；
3. 生产环境未配置 API_TOKENS → 500，且拒绝内置 dev token。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShopContext:
    shop_id: str
    actor: str
    role: str
    token_id: str


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"code": "unauthorized", "message": message})


def resolve_token(token: str) -> ShopContext:
    settings = get_settings()
    try:
        token_map = settings.token_map
    except ValueError as exc:
        raise HTTPException(status_code=500, detail={
            "code": "bad_token_config", "message": str(exc)}) from exc

    entry = token_map.get(token)
    if entry and entry.get("shop_id"):
        return ShopContext(shop_id=str(entry["shop_id"]), actor=str(entry.get("actor", "unknown")),
                           role=str(entry.get("role", "viewer")), token_id="config")

    # 生产环境 fail-closed：禁止 dev token 兜底
    if settings.is_production:
        raise _unauthorized("token 无效")

    if token == settings.default_api_token:
        return ShopContext(shop_id=settings.default_shop_id, actor=settings.default_actor,
                           role=settings.default_role, token_id="dev")

    raise _unauthorized("token 无效")


async def get_auth_context(authorization: str | None = Header(default=None)) -> ShopContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("缺少 Bearer token")
    return resolve_token(authorization.split(" ", 1)[1].strip())


def require_role(*roles: str, ctx: ShopContext) -> None:
    if ctx.role not in roles:
        raise HTTPException(status_code=403, detail={
            "code": "forbidden", "message": f"需要角色: {', '.join(roles)}"})
