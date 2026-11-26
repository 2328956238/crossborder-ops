import asyncio
import uuid

import httpx
from sqlalchemy import func, select

from crossborder_ops.models import Order, PlatformEvent
from crossborder_ops.integrations.http_client import AmazonClient
from crossborder_ops.services.events import handle_event
from crossborder_ops.core.rate_limiter import RedisLimiter


def ev(event_id, status, ts, order_id="O1"):
    return {"event_id": event_id, "shop_id": "S1", "type": "ORDER_CHANGE",
            "order_id": order_id, "status": status, "event_time": ts}


async def deliver(sm, event):
    async with sm() as s:
        return await handle_event(s, event)


async def test_concurrent_duplicate_only_stored_once(sessionmaker_):
    """同一事件并发投递 50 次，只入库一次。"""
    eid = f"E-{uuid.uuid4().hex[:10]}"
    order_id = f"O-{uuid.uuid4().hex[:10]}"
    e = ev(eid, "Pending", "2026-01-01T00:00:00+00:00", order_id=order_id)
    results = await asyncio.gather(*[deliver(sessionmaker_, e) for _ in range(50)])
    assert results.count("ok") == 1
    assert results.count("duplicate") == 49
    async with sessionmaker_() as s:
        n = (await s.execute(select(func.count()).select_from(PlatformEvent)
                             .where(PlatformEvent.event_id == eid))).scalar_one()
    assert n == 1


async def test_out_of_order_does_not_overwrite_newer(sessionmaker_):
    """新事件先到、旧事件后到，订单必须保持新状态。"""
    order_id = f"OO-{uuid.uuid4().hex[:8]}"
    await deliver(sessionmaker_, ev("E2", "Shipped", "2026-01-02T00:00:00+00:00", order_id=order_id))
    await deliver(sessionmaker_, ev("E3", "Pending", "2026-01-01T00:00:00+00:00", order_id=order_id))
    async with sessionmaker_() as s:
        o = (await s.execute(select(Order).where(Order.order_id == order_id))).scalar_one()
    assert o.status == "Shipped"
    assert o.version == 1  # 旧事件没有触发更新


async def test_retry_on_429_respects_retry_after(monkeypatch, redis_client):
    """前两次 429，第三次成功；按 Retry-After 等待。"""
    calls = {"n": 0}
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("crossborder_ops.integrations.http_client.asyncio.sleep", fake_sleep)
    limiter = RedisLimiter(redis_client, rate=100, burst=100)
    client = AmazonClient("http://x", limiter, transport=httpx.MockTransport(handler))
    data = await client.get("/orders", "S1", "orders")
    assert data == {"ok": True}
    assert calls["n"] == 3
    assert sleeps == [0.5, 0.5]
    assert client.stats["throttled_429"] == 2
