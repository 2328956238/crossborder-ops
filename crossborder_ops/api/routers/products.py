"""商品路由（shop_id 只来自认证上下文）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import ProductCreate, ProductUpdate
from ...services import catalog as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("")
async def list_products(status: str | None = Query(default=None, max_length=16),
                        limit: int = Query(default=50, ge=1, le=200),
                        offset: int = Query(default=0, ge=0),
                        session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(get_auth_context)):
    items = await service.list_products(session, ctx.shop_id, status=status,
                                        limit=limit, offset=offset)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/{sku}")
async def get_product(sku: str, session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.get_product(session, ctx.shop_id, sku)}


@router.post("", status_code=201)
async def create_product(payload: ProductCreate, session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.create_product(session, ctx.shop_id, payload)}


@router.patch("/{sku}")
async def update_product(sku: str, payload: ProductUpdate,
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.update_product(session, ctx.shop_id, sku, payload)}
