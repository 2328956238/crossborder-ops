# -*- coding: utf-8 -*-
"""webhook：去重、防乱序、参数校验、店铺白名单。"""
from __future__ import annotations

import uuid


def _event(event_id: str, status: str, ts: str, order_id: str = "W1", shop: str = "S1") -> dict:
    return {"shop_id": shop, "event_id": event_id, "type": "ORDER_CHANGE",
            "event_time": ts, "order_id": order_id, "status": status}


async def test_duplicate_event_only_stored_once(api):
    eid = f"e-{uuid.uuid4().hex}"
    first = await api.post("/webhook/amazon", json=_event(eid, "Pending",
                                                         "2026-02-01T00:00:00+00:00"))
    second = await api.post("/webhook/amazon", json=_event(eid, "Pending",
                                                          "2026-02-01T00:00:00+00:00"))
    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "duplicate"


async def test_out_of_order_keeps_newer_status(api):
    order_id = f"O-{uuid.uuid4().hex[:8]}"
    await api.post("/webhook/amazon", json=_event(f"a-{uuid.uuid4().hex}", "Shipped",
                                                 "2026-02-02T00:00:00+00:00", order_id=order_id))
    await api.post("/webhook/amazon", json=_event(f"b-{uuid.uuid4().hex}", "Pending",
                                                 "2026-02-01T00:00:00+00:00", order_id=order_id))
    from sqlalchemy import select

    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import Order

    async with get_sessionmaker()() as session:
        async with session.begin():
            order = (await session.execute(
                select(Order).where(Order.order_id == order_id))).scalar_one()
            assert order.status == "Shipped"
            assert order.version == 1


async def test_invalid_payload_returns_422(api):
    r = await api.post("/webhook/amazon", json={"shop_id": "S1", "event_id": "x"})
    assert r.status_code == 422


async def test_unknown_shop_rejected_when_allowlist_configured(api, monkeypatch):
    from crossborder_ops.config import get_settings

    monkeypatch.setenv("WEBHOOK_ALLOWED_SHOPS", "S1")
    get_settings.cache_clear()
    try:
        r = await api.post("/webhook/amazon", json=_event(f"z-{uuid.uuid4().hex}", "Pending",
                                                         "2026-03-01T00:00:00+00:00",
                                                         shop="S9"))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "shop_not_allowed"
    finally:
        get_settings.cache_clear()
