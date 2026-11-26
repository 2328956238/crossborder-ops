"""统一角色权限：viewer 只读；operator 可执行业务写与提交审批；admin 管店铺/授权/高风险审批。

API 层用 `require_role(...)` 依赖；Service 层用 `ensure_role(ctx, ...)`。
两边都校验，避免"绕过路由直接调 Service"的越权写入。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

from .security import ShopContext, get_auth_context

READ_ROLES = ("viewer", "operator", "admin")
WRITE_ROLES = ("operator", "admin")
ADMIN_ROLES = ("admin",)


def ensure_role(ctx: ShopContext, *roles: str) -> None:
    if ctx.role not in roles:
        raise HTTPException(status_code=403, detail={
            "code": "forbidden",
            "message": f"需要角色: {', '.join(roles)}，当前: {ctx.role}",
        })


def require_role(*roles: str):
    """FastAPI 依赖工厂：`Depends(require_role("operator", "admin"))`。"""

    async def _dependency(ctx: ShopContext = Depends(get_auth_context)) -> ShopContext:
        ensure_role(ctx, *roles)
        return ctx

    return _dependency
