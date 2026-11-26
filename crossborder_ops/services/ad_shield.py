"""广告盾服务：规则结果落库、风险事件状态流转、告警去重。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import NotFoundError, ValidationError
from ..repositories import ads as repo
from . import ad_shield_rules as rules

ALLOWED_TRANSITIONS = {
    "open": {"acknowledged", "resolved"},
    "acknowledged": {"resolved"},
    "resolved": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dict(event) -> dict:
    return {"id": event.id, "rule_code": event.rule_code, "severity": event.severity,
            "entity_type": event.entity_type, "entity_id": event.entity_id,
            "window_key": event.window_key, "status": event.status,
            "detail": event.detail, "detected_at": event.detected_at,
            "acked_by": event.acked_by, "resolved_by": event.resolved_by}


async def record_signals(session: AsyncSession, shop_id: str, signals: list[rules.Signal],
                         *, channel: str = "log") -> list[str]:
    """落库风险事件；重复（同规则+实体+窗口）直接跳过并返回空列表（告警抑制）。"""
    created: list[str] = []
    for signal in signals:
        data = {"rule_code": signal.rule_code, "severity": signal.severity,
                "entity_type": signal.entity_type, "entity_id": signal.entity_id,
                "window_key": signal.window_key, "status": "open",
                "detail": signal.detail, "detected_at": _now()}
        event = await repo.insert_risk_event(session, shop_id, data)
        if event is None:
            continue
        await repo.insert_alert(session, shop_id, {
            "risk_event_id": event.id, "channel": channel,
            "status": "pending",
            "dedupe_key": f"{shop_id}:{signal.rule_code}:{signal.entity_id}:{signal.window_key}",
            "payload": {"rule_code": signal.rule_code, "severity": signal.severity},
        })
        created.append(event.id)
    return created


async def list_events(session: AsyncSession, shop_id: str, status: str | None = None) -> list[dict]:
    return [_to_dict(e) for e in await repo.list_risk_events(session, shop_id, status=status)]


async def get_event(session: AsyncSession, shop_id: str, event_id: str) -> dict:
    event = await repo.get_risk_event(session, shop_id, event_id)
    if event is None:
        raise NotFoundError(f"风险事件不存在: {event_id}")
    return _to_dict(event)


async def update_status(session: AsyncSession, shop_id: str, event_id: str, target: str,
                        actor: str) -> dict:
    target = target.strip().lower()
    if target not in {"acknowledged", "resolved"}:
        raise ValidationError("只支持 acknowledged / resolved")
    event = await repo.get_risk_event(session, shop_id, event_id)
    if event is None:
        raise NotFoundError(f"风险事件不存在: {event_id}")
    if target not in ALLOWED_TRANSITIONS.get(event.status, set()):
        raise ValidationError(f"非法状态流转: {event.status} → {target}")
    await repo.set_risk_status(session, event, target, actor)
    return _to_dict(event)


async def list_alerts(session: AsyncSession, shop_id: str) -> list[dict]:
    return [{"id": a.id, "risk_event_id": a.risk_event_id, "channel": a.channel,
             "status": a.status, "dedupe_key": a.dedupe_key}
            for a in await repo.list_alerts(session, shop_id)]
