"""广告域路由：读 viewer+；账户登记/指标写入为低风险直接写（operator+），全部审计。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import AccountCreate, InsightUpsert
from ...services import advertising as service
from ..deps import get_request_id

router = APIRouter(prefix="/api/v1/advertising", tags=["advertising"])
_READ = require_role("viewer", "operator", "admin")
_WRITE = require_role("operator", "admin")


@router.get("/accounts")
async def list_accounts(session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"shop_id": ctx.shop_id,
                                 "items": await service.list_accounts(session, ctx.shop_id)}}


@router.post("/accounts", status_code=201)
async def create_account(payload: AccountCreate, request: Request,
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(_WRITE)):
    data = await service.create_account(session, ctx, payload)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="advertising.account.create", entity_type="ad_account",
        entity_id=data["external_id"], before=None, after=data,
        request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.get("/campaigns")
async def list_campaigns(session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"items": await service.list_campaigns(session, ctx.shop_id)}}


@router.get("/adsets")
async def list_adsets(session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"items": await service.list_adsets(session, ctx.shop_id)}}


@router.get("/ads")
async def list_ads(session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"items": await service.list_ads(session, ctx.shop_id)}}


@router.post("/insights", status_code=201)
async def upsert_insight(payload: InsightUpsert, request: Request,
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(_WRITE)):
    data = await service.upsert_insight(session, ctx, payload)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="advertising.insight.upsert", entity_type="ad_insight",
        entity_id=f"{data['level']}:{data['entity_external_id']}:{data['date']}",
        before=None, after=data, request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.get("/metrics")
async def metrics(date_from: date = Query(...), date_to: date = Query(...),
                  session: AsyncSession = Depends(get_session),
                  ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": await service.metrics(session, ctx.shop_id,
                                                       date_from=date_from, date_to=date_to)}
