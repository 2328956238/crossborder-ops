"""经营报表路由（日期区间 + shop 隔离）。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...services import reports as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/sales")
async def sales(date_from: date = Query(...), date_to: date = Query(...),
                session: AsyncSession = Depends(get_session),
                ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.sales_summary(session, ctx.shop_id,
                                                            date_from, date_to)}


@router.get("/ads")
async def ads(date_from: date = Query(...), date_to: date = Query(...),
              session: AsyncSession = Depends(get_session),
              ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.ad_summary(session, ctx.shop_id,
                                                         date_from, date_to)}


@router.get("/inventory-warnings")
async def inventory_warnings(session: AsyncSession = Depends(get_session),
                             ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.inventory_warnings(session, ctx.shop_id)}}


@router.get("/overview")
async def overview(date_from: date = Query(...), date_to: date = Query(...),
                   shops: str | None = Query(default=None,
                                             description="仅 admin 可查多店铺，逗号分隔"),
                   session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    shop_ids = [ctx.shop_id]
    if shops:
        if ctx.role != "admin":
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail={
                "code": "forbidden", "message": "多店铺汇总需要 admin"})
        shop_ids = [s.strip() for s in shops.split(",") if s.strip()]
    return {"ok": True, "data": {"items": await service.multi_shop_overview(
        session, shop_ids, date_from, date_to)}}


@router.get("/top-products")
async def top_products(date_from: date = Query(...), date_to: date = Query(...),
                       limit: int = Query(default=10, ge=1, le=100),
                       session: AsyncSession = Depends(get_session),
                       ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.top_products(
        session, ctx.shop_id, date_from, date_to, limit)}}


@router.get("/ads/trend")
async def ads_trend(date_from: date = Query(...), date_to: date = Query(...),
                    session: AsyncSession = Depends(get_session),
                    ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.ad_trend(
        session, ctx.shop_id, date_from, date_to)}}
