# -*- coding: utf-8 -*-
"""阶段 5 报表测试：商品排行 / 广告趋势 / 日期区间 / 多店铺隔离。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.conftest import auth


async def _seed_order_with_items(session, shop_id: str, items: list[tuple[str, int, str]],
                                 days_ago: int = 0) -> str:
    from crossborder_ops.models import Order, OrderItem

    order_id = f"ORD-{uuid.uuid4().hex[:8]}"
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.add(Order(shop_id=shop_id, order_id=order_id, status="SHIPPED",
                      last_update_time=created.isoformat(), version=1,
                      total_amount=Decimal("0"), currency="USD", created_at=created))
    for sku, qty, amount in items:
        session.add(OrderItem(shop_id=shop_id, order_id=order_id, sku=sku, quantity=qty,
                              unit_amount=Decimal(amount), currency="USD",
                              created_at=created))
    await session.flush()
    return order_id


async def test_top_products_ranking_and_isolation(api, two_shops, sessionmaker_):
    sku_a = f"A-{uuid.uuid4().hex[:6]}"
    sku_b = f"B-{uuid.uuid4().hex[:6]}"
    async with sessionmaker_() as session:
        async with session.begin():
            await _seed_order_with_items(session, "S2", [(sku_a, 5, "10.00"), (sku_b, 1, "60.00")])
            # 另一个店的数据不能混进来
            await _seed_order_with_items(session, "S1", [(sku_a, 100, "10.00")])

    today = datetime.now(timezone.utc).date()
    r = await api.get(
        f"/api/v1/reports/top-products?date_from={today}&date_to={today}",
        headers=auth(two_shops["S2"]))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    by_sku = {i["sku"]: i for i in items}
    assert sku_a in by_sku and sku_b in by_sku
    # sku_b 营收 60 > sku_a 50 → 排第一
    assert items[0]["sku"] == sku_b
    assert by_sku[sku_a]["quantity"] == 5
    assert by_sku[sku_a]["revenue"] == "50.0000"


async def test_top_products_date_range_excludes_old_orders(api, two_shops, sessionmaker_):
    sku = f"OLD-{uuid.uuid4().hex[:6]}"
    async with sessionmaker_() as session:
        async with session.begin():
            await _seed_order_with_items(session, "S2", [(sku, 1, "10.00")], days_ago=30)

    today = datetime.now(timezone.utc).date()
    r = await api.get(
        f"/api/v1/reports/top-products?date_from={today}&date_to={today}&limit=100",
        headers=auth(two_shops["S2"]))
    assert all(i["sku"] != sku for i in r.json()["data"]["items"])

    # limit 校验
    bad = await api.get(
        f"/api/v1/reports/top-products?date_from={today}&date_to={today}&limit=0",
        headers=auth(two_shops["S2"]))
    assert bad.status_code == 422


async def test_ad_trend_daily_series(api, two_shops):
    today = datetime.now(timezone.utc).date()
    await api.post("/api/v1/advertising/insights", headers=auth(two_shops["S1"]),
                   json={"level": "account", "entity_external_id": "act_trend",
                         "date": today.isoformat(), "impressions": 500, "clicks": 25,
                         "spend": 10, "conversions": 2, "revenue": 40})
    r = await api.get(
        f"/api/v1/reports/ads/trend?date_from={today}&date_to={today}",
        headers=auth(two_shops["S1"]))
    assert r.status_code == 200
    series = r.json()["data"]["items"]
    assert len(series) == 1
    assert series[0]["spend"] == "10.0000"
    assert series[0]["revenue"] == "40.0000"
    assert series[0]["acos"] == 0.25


async def test_overview_contains_roas_and_acos(api, two_shops):
    today = datetime.now(timezone.utc).date()
    r = await api.get(
        f"/api/v1/reports/overview?date_from={today}&date_to={today}",
        headers=auth(two_shops["S1"]))
    assert r.status_code == 200
    row = r.json()["data"]["items"][0]
    assert {"shop_id", "orders", "revenue", "ad_spend", "roas", "acos"} <= set(row)
