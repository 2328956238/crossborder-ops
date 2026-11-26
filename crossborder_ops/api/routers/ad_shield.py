"""广告盾路由：风险事件查询与状态流转、告警查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
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
