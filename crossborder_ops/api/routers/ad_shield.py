"""广告盾路由：读 viewer+；风险处置 operator+（审计）；巡检仅 admin（审计）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session, get_sessionmaker
from ...integrations.meta import build_meta_client
from ...integrations.meta import oauth as meta_oauth
from ...repositories import ads as ads_repo
from ...services import ad_shield_patrol
from ...services import ad_shield as service
from ..deps import get_request_id

router = APIRouter(prefix="/api/v1/ad-shield", tags=["ad-shield"])
_READ = require_role("viewer", "operator", "admin")
_WRITE = require_role("operator", "admin")


@router.get("/risks")
async def list_risks(status: str | None = Query(default=None, max_length=16),
                     session: AsyncSession = Depends(get_session),
                     ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"shop_id": ctx.shop_id,
                                 "items": await service.list_events(session, ctx.shop_id, status)}}


@router.get("/risks/{event_id}")
async def get_risk(event_id: str, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": await service.get_event(session, ctx.shop_id, event_id)}


@router.post("/risks/{event_id}/ack")
async def ack_risk(event_id: str, request: Request,
                   session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(_WRITE)):
    before = await service.get_event(session, ctx.shop_id, event_id)
    data = await service.update_status(session, ctx.shop_id, event_id,
                                       "acknowledged", ctx.actor)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="ad_shield.risk.ack", entity_type="risk_event", entity_id=event_id,
        before={"status": before["status"]}, after={"status": data["status"]},
        request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.post("/risks/{event_id}/resolve")
async def resolve_risk(event_id: str, request: Request,
                       session: AsyncSession = Depends(get_session),
                       ctx: ShopContext = Depends(_WRITE)):
    before = await service.get_event(session, ctx.shop_id, event_id)
    data = await service.update_status(session, ctx.shop_id, event_id,
                                       "resolved", ctx.actor)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="ad_shield.risk.resolve", entity_type="risk_event", entity_id=event_id,
        before={"status": before["status"]}, after={"status": data["status"]},
        request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.get("/alerts")
async def list_alerts(session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(_READ)):
    return {"ok": True, "data": {"items": await service.list_alerts(session, ctx.shop_id)}}


@router.get("/reviews")
async def list_reviews(session: AsyncSession = Depends(get_session),
                       ctx: ShopContext = Depends(_READ)):
    rows = await ads_repo.list_reviews(session, ctx.shop_id)
    return {"ok": True, "data": {"items": [
        {"ad_id": r.ad_id, "status": r.status, "reason_code": r.reason_code,
         "reason_text": r.reason_text, "manual_required": r.manual_required,
         "fetched_at": r.fetched_at} for r in rows]}}


@router.post("/patrol")
async def run_patrol(request: Request,
                     ctx: ShopContext = Depends(require_role("admin")),
                     sm=Depends(get_sessionmaker)):
    async with sm() as session:
        token = await meta_oauth.load_token(session, ctx.shop_id)
    client = build_meta_client(token)
    result = await ad_shield_patrol.run_patrol(sm, ctx.shop_id, client)
    async with sm() as session:
        async with session.begin():
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action="ad_shield.patrol", entity_type="shop", entity_id=ctx.shop_id,
                before=None, after={"accounts": result.get("accounts"),
                                    "reviews": result.get("reviews"),
                                    "signals": result.get("signals"),
                                    "created_events": result.get("created_events"),
                                    "alerts": result.get("alerts")},
                request_id=get_request_id(request))
    return {"ok": True, "data": result}
