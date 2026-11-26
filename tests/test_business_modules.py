# -*- coding: utf-8 -*-
"""阶段 2 业务模块测试：商品 / 订单 / 库存 / 广告 / 广告盾 / 报表 + shop 隔离。"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from crossborder_ops.services import ad_shield_rules as rules
from tests.conftest import auth


async def _webhook_order(api, shop_id: str, order_id: str) -> None:
    payload = {"shop_id": shop_id, "event_id": f"e-{uuid.uuid4().hex}", "type": "ORDER_CHANGE",
               "event_time": "2026-03-01T00:00:00+00:00", "order_id": order_id,
               "status": "SHIPPED"}
    r = await api.post("/webhook/amazon", json=payload)
    assert r.json()["status"] == "ok"


# ---------------- products ----------------
async def test_product_crud_and_isolation(api, two_shops):
    sku = f"SKU-{uuid.uuid4().hex[:6]}"
    created = await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                             json={"sku": sku, "title": "测试商品", "price": 19.9})
    assert created.status_code == 201
    assert created.json()["data"]["shop_id"] == "S1"

    # 同店重复 → 409
    dup = await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                         json={"sku": sku, "title": "重复"})
    assert dup.status_code == 409

    # 跨店不可见 → 404
    other = await api.get(f"/api/v1/products/{sku}", headers=auth(two_shops["S2"]))
    assert other.status_code == 404

    # 参数校验：负价格 → 422
    bad = await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                         json={"sku": "X1", "title": "x", "price": -1})
    assert bad.status_code == 422

    # 整改后：售价修改必须走审批（202 返回 DRAFT 操作，不直接改数据）
    submitted = await api.patch(f"/api/v1/products/{sku}", headers=auth(two_shops["S1"]),
                                json={"price": 15.5})
    assert submitted.status_code == 202
    operation = submitted.json()["data"]
    assert operation["status"] == "DRAFT"
    assert operation["before_snapshot"]["price"] == "19.9000"
    # 审批前数据不变
    unchanged = await api.get(f"/api/v1/products/{sku}", headers=auth(two_shops["S1"]))
    assert unchanged.json()["data"]["price"] == "19.9000"

    op_id = operation["operation_id"]
    await api.post(f"/api/v1/operations/{op_id}/submit", headers=auth(two_shops["S1"]),
                   json={})
    approved = await api.post(f"/api/v1/operations/{op_id}/approve",
                              headers=auth(two_shops["S1"]))
    assert approved.json()["data"]["result"] == "approved"
    executed = await api.post(f"/api/v1/operations/{op_id}/execute",
                              headers=auth(two_shops["S1"]))
    assert executed.json()["data"]["result"] == "executed"
    assert executed.json()["data"]["execution_target"] == "db"
    after = await api.get(f"/api/v1/products/{sku}", headers=auth(two_shops["S1"]))
    assert after.json()["data"]["price"] == "15.5000"


# ---------------- orders ----------------
async def test_orders_list_stats_isolation(api, two_shops):
    order_id = f"O-{uuid.uuid4().hex[:8]}"
    await _webhook_order(api, "S1", order_id)

    listing = await api.get("/api/v1/orders", headers=auth(two_shops["S1"]))
    assert listing.status_code == 200
    assert any(o["order_id"] == order_id for o in listing.json()["data"]["items"])

    # S2 看不到 S1 的订单
    other = await api.get("/api/v1/orders", headers=auth(two_shops["S2"]))
    assert all(o["order_id"] != order_id for o in other.json()["data"]["items"])

    stats = await api.get("/api/v1/orders/stats?days=30", headers=auth(two_shops["S1"]))
    assert stats.json()["data"]["days"] == 30

    missing = await api.get("/api/v1/orders/NOT-EXIST", headers=auth(two_shops["S1"]))
    assert missing.status_code == 404


# ---------------- inventory ----------------
async def test_inventory_upsert_adjust_and_validation(api, two_shops):
    sku = f"INV-{uuid.uuid4().hex[:6]}"
    put = await api.put(f"/api/v1/inventory/{sku}", headers=auth(two_shops["S1"]),
                        json={"sku": sku, "on_hand": 10, "reserved": 2, "safety_stock": 5})
    assert put.status_code == 200
    assert put.json()["data"]["available"] == 8

    adjusted = await api.post(f"/api/v1/inventory/{sku}/adjust", headers=auth(two_shops["S1"]),
                              json={"on_hand_delta": -4, "reserved_delta": 1})
    assert adjusted.json()["data"]["on_hand"] == 6
    assert adjusted.json()["data"]["available"] == 3

    # 可售低于安全库存 → 低库存列表命中
    low = await api.get("/api/v1/inventory/low-stock", headers=auth(two_shops["S1"]))
    assert any(i["sku"] == sku and i["shortage"] > 0 for i in low.json()["data"]["items"])

    # reserved > on_hand → 422
    bad = await api.post(f"/api/v1/inventory/{sku}/adjust", headers=auth(two_shops["S1"]),
                         json={"reserved_delta": 100})
    assert bad.status_code == 422

    # 跨店不可见
    other = await api.post(f"/api/v1/inventory/{sku}/adjust", headers=auth(two_shops["S2"]),
                           json={"on_hand_delta": 1})
    assert other.status_code == 404


# ---------------- advertising ----------------
async def test_ad_account_and_insight_idempotency(api, two_shops):
    ext = f"act_{uuid.uuid4().hex[:8]}"
    created = await api.post("/api/v1/advertising/accounts", headers=auth(two_shops["S1"]),
                             json={"external_id": ext, "name": "Meta 账户", "platform": "meta"})
    assert created.status_code == 201

    day = "2030-06-01"
    payload = {"level": "account", "entity_external_id": ext, "date": day,
               "impressions": 1000, "clicks": 20, "spend": 10, "conversions": 2, "revenue": 50}
    first = await api.post("/api/v1/advertising/insights", headers=auth(two_shops["S1"]),
                           json=payload)
    assert first.status_code == 201
    # 同 key 再写：幂等更新而不是插两条
    payload["clicks"] = 30
    await api.post("/api/v1/advertising/insights", headers=auth(two_shops["S1"]), json=payload)

    metrics = await api.get(
        f"/api/v1/advertising/metrics?date_from={day}&date_to={day}",
        headers=auth(two_shops["S1"]))
    data = metrics.json()["data"]
    assert data["clicks"] == 30
    assert data["roas"] == pytest.approx(5.0)
    assert data["acos"] == pytest.approx(0.2)

    # 跨店看不到
    other = await api.get(f"/api/v1/advertising/metrics?date_from={day}&date_to={day}",
                          headers=auth(two_shops["S2"]))
    assert other.json()["data"]["clicks"] == 0


# ---------------- ad_shield 规则 ----------------
def test_spend_drop_is_warn_not_ban():
    signals = rules.evaluate_spend("S1", "act_1", "2026-03-01",
                                   spend_today=1, spend_avg7=10)
    assert len(signals) == 1
    assert signals[0].severity == "warn"
    assert "不等于" in signals[0].detail["note"]


def test_api_errors_are_distinguished():
    codes = {status: rules.evaluate_api_error("act_1", "w", status)[0].rule_code
             for status in (401, 403, 429, 500)}
    assert len(set(codes.values())) == 4
    assert codes[401] == "R401_TOKEN_INVALID"
    assert rules.evaluate_api_error("act_1", "w", 429)[0].severity == "info"


def test_review_without_reason_requires_manual():
    signals = rules.evaluate_review("S1", "ad_1", "2026-03-01", status="REJECTED",
                                    reason_code=None, reason_text=None)
    assert signals[0].detail["manual_required"] is True


async def test_record_signals_dedupes_and_alerts(api, two_shops, sessionmaker_):
    from crossborder_ops.services import ad_shield as shield

    signals = rules.evaluate_api_error("act_dedup", "2026-03-02", 429)
    async with sessionmaker_() as session:
        async with session.begin():
            created = await shield.record_signals(session, "S1", signals)
            again = await shield.record_signals(session, "S1", signals)
    assert len(created) == 1
    assert again == []      # 同窗口重复检测被抑制

    listed = await api.get("/api/v1/ad-shield/risks", headers=auth(two_shops["S1"]))
    assert any(e["rule_code"] == "R429_RATE_LIMIT" for e in listed.json()["data"]["items"])

    alerts = await api.get("/api/v1/ad-shield/alerts", headers=auth(two_shops["S1"]))
    assert any(a["status"] == "pending" for a in alerts.json()["data"]["items"])


async def test_risk_status_transitions(api, two_shops, sessionmaker_):
    from crossborder_ops.services import ad_shield as shield

    async with sessionmaker_() as session:
        async with session.begin():
            created = await shield.record_signals(
                session, "S1", rules.evaluate_ctr("S1", "ad_x", "2026-03-03",
                                                   ctr_today=0.001, ctr_avg7=0.01))
    event_id = created[0]

    ack = await api.post(f"/api/v1/ad-shield/risks/{event_id}/ack",
                         headers=auth(two_shops["S1"]))
    assert ack.json()["data"]["status"] == "acknowledged"
    resolved = await api.post(f"/api/v1/ad-shield/risks/{event_id}/resolve",
                              headers=auth(two_shops["S1"]))
    assert resolved.json()["data"]["status"] == "resolved"
    # 已解决再 ack → 422
    again = await api.post(f"/api/v1/ad-shield/risks/{event_id}/ack",
                           headers=auth(two_shops["S1"]))
    assert again.status_code == 422


# ---------------- reports ----------------
async def test_reports_date_range_and_isolation(api, two_shops):
    today = date.today()
    day = today.isoformat()
    await api.post("/api/v1/advertising/insights", headers=auth(two_shops["S1"]),
                   json={"level": "account", "entity_external_id": "act_rep", "date": day,
                         "impressions": 200, "clicks": 10, "spend": 5,
                         "conversions": 1, "revenue": 20})
    ads = await api.get(f"/api/v1/reports/ads?date_from={day}&date_to={day}",
                        headers=auth(two_shops["S1"]))
    assert ads.json()["data"]["spend"] == "5.0000"

    sales = await api.get(f"/api/v1/reports/sales?date_from={day}&date_to={day}",
                          headers=auth(two_shops["S1"]))
    assert "revenue" in sales.json()["data"]

    # 非 admin 不能查多店铺
    viewer = await api.get(
        f"/api/v1/reports/overview?date_from={day}&date_to={day}&shops=S1,S2",
        headers=auth(two_shops["viewer"]))
    assert viewer.status_code == 403

    admin = await api.get(
        f"/api/v1/reports/overview?date_from={day}&date_to={day}&shops=S1,S2",
        headers=auth(two_shops["S1"]))
    assert admin.status_code == 200
    assert {r["shop_id"] for r in admin.json()["data"]["items"]} == {"S1", "S2"}
