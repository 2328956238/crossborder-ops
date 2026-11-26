"""告警通知：log（默认）或 webhook；发送后回写 alerts 状态，失败不阻塞巡检。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Alert

logger = logging.getLogger(__name__)


class LogNotifier:
    channel = "log"

    async def send(self, alert: Alert) -> None:
        logger.warning("ALERT shop=%s rule=%s severity=%s status=%s",
                       alert.shop_id, alert.payload.get("rule_code"),
                       alert.payload.get("severity"), alert.status)


class WebhookNotifier:
    channel = "webhook"

    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None):
        self.url = url
        self._transport = transport

    async def send(self, alert: Alert) -> None:
        payload = {"dedupe_key": alert.dedupe_key, "shop_id": alert.shop_id,
                   "risk_event_id": alert.risk_event_id,
                   "rule_code": alert.payload.get("rule_code"),
                   "severity": alert.payload.get("severity")}
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as http:
            response = await http.post(self.url, json=payload)
            response.raise_for_status()


def build_notifier(transport: httpx.AsyncBaseTransport | None = None):
    settings = get_settings()
    if settings.notify_channel == "webhook" and settings.notify_webhook_url:
        return WebhookNotifier(settings.notify_webhook_url, transport=transport)
    return LogNotifier()


async def deliver_pending(session: AsyncSession, shop_id: str, *,
                          notifier=None) -> dict:
    notifier = notifier or build_notifier()
    async with session.begin():
        alerts = list((await session.execute(
            select(Alert).where(Alert.shop_id == shop_id, Alert.status == "pending")
            .order_by(Alert.id))).scalars().all())
        sent = failed = 0
        for alert in alerts:
            try:
                await notifier.send(alert)
                alert.status = "sent"
                alert.sent_at = datetime.now(timezone.utc).isoformat()
                sent += 1
            except Exception as exc:  # noqa: BLE001 - 通知失败不能影响巡检
                alert.status = "failed"
                logger.warning("alert 发送失败 id=%s: %s", alert.id, type(exc).__name__)
                failed += 1
    return {"channel": notifier.channel, "sent": sent, "failed": failed}
