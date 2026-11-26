"""店铺路由：列表/详情/创建（创建仅 admin）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import ShopCreate
from ...services import shops as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/shops", tags=["shops"])


@router.get("")
async def list_shops(session: AsyncSession = Depends(get_session),
                     ctx: ShopContext = Depends(get_auth_context)):
    # 只返回当前 token 对应店铺，避免跨租户枚举
    current = await service.get_shop(session, ctx.shop_id)
    return {"ok": True, "data": {"items": [current], "current": ctx.shop_id}}


@router.get("/{shop_id}")
async def get_shop(shop_id: str, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    if shop_id != ctx.shop_id:
        raise HTTPException(status_code=403, detail={"code": "forbidden_shop",
                                                     "message": "只能查看当前店铺"})
    return {"ok": True, "data": await service.get_shop(session, shop_id)}


@router.post("", status_code=201)
async def create_shop(payload: ShopCreate, session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    if ctx.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "需要 admin"})
    return {"ok": True, "data": await service.create_shop(session, payload)}
