"""库存路由：列表 / 低库存 / upsert / 增量调整。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import InventoryAdjust, InventoryUpsert
from ...services import inventory as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("")
async def list_inventory(low_only: bool = Query(default=False),
                         limit: int = Query(default=100, ge=1, le=500),
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    items = await service.list_inventory(session, ctx.shop_id, low_only=low_only, limit=limit)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/low-stock")
async def low_stock(session: AsyncSession = Depends(get_session),
                    ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.low_stock(session, ctx.shop_id)}}


@router.put("/{sku}")
async def upsert_inventory(sku: str, payload: InventoryUpsert,
                           session: AsyncSession = Depends(get_session),
                           ctx: ShopContext = Depends(get_auth_context)):
    payload = payload.model_copy(update={"sku": sku})
    return {"ok": True, "data": await service.upsert(session, ctx.shop_id, payload)}


@router.post("/{sku}/adjust")
async def adjust_inventory(sku: str, payload: InventoryAdjust,
                           session: AsyncSession = Depends(get_session),
                           ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.adjust(session, ctx.shop_id, sku, payload)}
