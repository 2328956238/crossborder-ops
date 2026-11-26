"""平台 webhook：事件去重与订单同步入口。

安全（阶段 2 增强）：生产环境必须配置 webhook_allowed_shops 白名单；
验签（HMAC）在阶段 2 接入，当前仅校验店铺白名单。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session
from ...schemas.webhook import EventPayload
from ...services.events import handle_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhook/amazon")
async def receive(event: EventPayload, session: AsyncSession = Depends(get_session)):
    settings = get_settings()
    allowed = {s.strip() for s in settings.webhook_allowed_shops.split(",") if s.strip()}
    if allowed and event.shop_id not in allowed:
        raise HTTPException(status_code=403, detail={
            "code": "shop_not_allowed", "message": "店铺不在 webhook 白名单内"})
    if settings.is_production and not allowed:
        raise HTTPException(status_code=500, detail={
            "code": "webhook_not_configured", "message": "生产环境必须配置 WEBHOOK_ALLOWED_SHOPS"})
    status = await handle_event(session, event.to_dict())
    return {"status": status}
