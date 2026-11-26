"""广告域路由：账户 / Campaign / AdSet / Ad / Insights。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import AccountCreate, InsightUpsert
from ...services import advertising as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/advertising", tags=["advertising"])


@router.get("/accounts")
async def list_accounts(session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"shop_id": ctx.shop_id,
                                 "items": await service.list_accounts(session, ctx.shop_id)}}


@router.post("/accounts", status_code=201)
async def create_account(payload: AccountCreate, session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.create_account(session, ctx.shop_id, payload)}


@router.get("/campaigns")
async def list_campaigns(session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.list_campaigns(session, ctx.shop_id)}}


@router.get("/adsets")
async def list_adsets(session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.list_adsets(session, ctx.shop_id)}}


@router.get("/ads")
async def list_ads(session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.list_ads(session, ctx.shop_id)}}


@router.post("/insights", status_code=201)
async def upsert_insight(payload: InsightUpsert, session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.upsert_insight(session, ctx.shop_id, payload)}


@router.get("/metrics")
async def metrics(date_from: date = Query(...), date_to: date = Query(...),
                  session: AsyncSession = Depends(get_session),
                  ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.metrics(session, ctx.shop_id,
                                                       date_from=date_from, date_to=date_to)}
