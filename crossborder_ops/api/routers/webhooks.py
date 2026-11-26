"""平台 webhook：HMAC 验签 + 时间戳防重放 + 店铺白名单 + 不自动建店。

签名格式（平台适配器隔离在 `webhooks_signing.py`，不同平台可扩展）：
    X-Timestamp: <unix seconds>
    X-Signature: sha256=<hex(hmac_sha256(secret, f"{timestamp}.{raw_body}"))>
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core import audit as audit_core
from ...db import get_session, get_sessionmaker
from ...repositories import business as repo
from ...schemas.webhook import EventPayload
from ...services.events import handle_event
from ...services.webhooks_signing import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhook/amazon")
async def receive(request: Request, session: AsyncSession = Depends(get_session)):
    import json

    settings = get_settings()
    raw_body = await request.body()

    allowed = {s.strip() for s in settings.webhook_allowed_shops.split(",") if s.strip()}
    if settings.is_production and not allowed:
        raise HTTPException(status_code=500, detail={
            "code": "webhook_not_configured", "message": "生产环境必须配置 WEBHOOK_ALLOWED_SHOPS"})

    verify_signature(
        secret=settings.webhook_secret,
        timestamp=request.headers.get("X-Timestamp"),
        signature=request.headers.get("X-Signature"),
        body=raw_body,
        max_skew_seconds=settings.webhook_max_skew_seconds,
        required=bool(settings.webhook_secret) or settings.is_production,
    )

    try:
        payload = json.loads(raw_body)
        event = EventPayload.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail={
            "code": "validation_error", "message": "webhook 请求体不合法"}) from exc

    if allowed and event.shop_id not in allowed:
        raise HTTPException(status_code=403, detail={
            "code": "shop_not_allowed", "message": "店铺不在 webhook 白名单内"})

    # 只允许已注册店铺；绝不自动创建
    async with get_sessionmaker()() as lookup:
        async with lookup.begin():
            shop = await repo.get_shop(lookup, event.shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail={
            "code": "shop_not_found", "message": "店铺未注册，拒绝接收 webhook"})

    status = await handle_event(session, event.to_dict())
    try:
        async with get_sessionmaker()() as audit_session:
            async with audit_session.begin():
                await audit_core.record(
                    audit_session, shop_id=event.shop_id, actor="platform:webhook",
                    role="system", action="webhook.amazon", entity_type="platform_event",
                    entity_id=event.event_id, before=None,
                    after={"type": event.type, "status": status})
    except Exception:  # noqa: BLE001
        logger.exception("webhook 审计写入失败")
    return {"status": status}
