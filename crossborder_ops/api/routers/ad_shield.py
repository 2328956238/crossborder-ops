"""广告盾路由：风险事件查询与状态流转、告警查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session, get_sessionmaker
from ...integrations.meta import build_meta_client
from ...integrations.meta import oauth as meta_oauth
from ...repositories import ads as ads_repo
from ...services import ad_shield_patrol
from ...services import ad_shield as service
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/ad-shield", tags=["ad-shield"])


@router.get("/risks")
async def list_risks(status: str | None = Query(default=None, max_length=16),
                     session: AsyncSession = Depends(get_session),
                     ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"shop_id": ctx.shop_id,
                                 "items": await service.list_events(session, ctx.shop_id, status)}}


@router.get("/risks/{event_id}")
async def get_risk(event_id: str, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.get_event(session, ctx.shop_id, event_id)}


@router.post("/risks/{event_id}/ack")
async def ack_risk(event_id: str, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.update_status(
        session, ctx.shop_id, event_id, "acknowledged", ctx.actor)}


@router.post("/risks/{event_id}/resolve")
async def resolve_risk(event_id: str, session: AsyncSession = Depends(get_session),
                       ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": await service.update_status(
        session, ctx.shop_id, event_id, "resolved", ctx.actor)}


@router.get("/alerts")
async def list_alerts(session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": {"items": await service.list_alerts(session, ctx.shop_id)}}


@router.get("/reviews")
async def list_reviews(session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(get_auth_context)):
    rows = await ads_repo.list_reviews(session, ctx.shop_id)
    return {"ok": True, "data": {"items": [
        {"ad_id": r.ad_id, "status": r.status, "reason_code": r.reason_code,
         "reason_text": r.reason_text, "manual_required": r.manual_required,
         "fetched_at": r.fetched_at} for r in rows]}}


@router.post("/patrol")
async def run_patrol(ctx: ShopContext = Depends(get_auth_context),
                     sm=Depends(get_sessionmaker)):
    if ctx.role != "admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail={"code": "forbidden",
                                                     "message": "巡检需要 admin"})
    async with sm() as session:
        token = await meta_oauth.load_token(session, ctx.shop_id)
    client = build_meta_client(token)
    return {"ok": True, "data": await ad_shield_patrol.run_patrol(sm, ctx.shop_id, client)}
