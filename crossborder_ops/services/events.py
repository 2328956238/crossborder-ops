"""平台事件同步：webhook 去重 + 订单防乱序 upsert（同事务）。"""
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INSERT_EVENT = text("""
INSERT INTO platform_event (shop_id, event_id, type, payload)
VALUES (:shop_id, :event_id, :type, :payload)
ON CONFLICT (shop_id, event_id) DO NOTHING
""")

UPSERT_ORDER = text("""
INSERT INTO orders (shop_id, order_id, status, last_update_time, version)
VALUES (:shop_id, :order_id, :status, :ts, 1)
ON CONFLICT (shop_id, order_id) DO UPDATE
SET status = excluded.status,
    last_update_time = excluded.last_update_time,
    version = orders.version + 1
WHERE orders.last_update_time < excluded.last_update_time
""")


async def handle_event(session: AsyncSession, event: dict) -> str:
    """去重 + 防乱序在同一事务内完成。返回 duplicate / ok。"""
    async with session.begin():
        result = await session.execute(INSERT_EVENT, {
            "shop_id": event["shop_id"], "event_id": event["event_id"],
            "type": event["type"], "payload": json.dumps(event, ensure_ascii=False),
        })
        if result.rowcount == 0:
            return "duplicate"
        if event["type"] == "ORDER_CHANGE":
            await session.execute(UPSERT_ORDER, {
                "shop_id": event["shop_id"], "order_id": event["order_id"],
                "status": event["status"], "ts": event["event_time"],
            })
    return "ok"
