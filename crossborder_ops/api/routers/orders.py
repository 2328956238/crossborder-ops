"""订单路由：列表 / 详情 / 统计。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...services import orders as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("")
async def list_orders(status: str | None = Query(default=None, max_length=32),
                      limit: int = Query(default=50, ge=1, le=200),
                      offset: int = Query(default=0, ge=0),
                      session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    items = await service.list_orders(session, ctx.shop_id, status=status,
                                      limit=limit, offset=offset)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/stats")
async def order_stats(days: int = Query(default=7, ge=1, le=365),
                      session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.stats(session, ctx.shop_id, days=days)}


@router.get("/{order_id}")
async def get_order(order_id: str, session: AsyncSession = Depends(get_session),
                    ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.get_order(session, ctx.shop_id, order_id)}
