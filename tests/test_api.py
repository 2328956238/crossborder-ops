# -*- coding: utf-8 -*-
"""API 层：认证、shop 隔离、参数校验、synthetic 声明。"""
from __future__ import annotations

import uuid

import pytest
from tests.conftest import auth


async def test_requires_bearer_token(api):
    assert (await api.get("/api/v1/amazon/products")).status_code == 401


async def test_invalid_token_rejected(api):
    r = await api.get("/api/v1/amazon/products", headers=auth("nope"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


async def test_read_api_marks_synthetic(api, two_shops):
    r = await api.get("/api/v1/amazon/products", headers=auth(two_shops["S1"]))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["source"] == "synthetic"
    assert data["shop_id"] == "S1"
    assert "非真实" in data["note"]


async def test_shop_isolation_on_read(api, two_shops):
    r1 = await api.get("/api/v1/amazon/orders", headers=auth(two_shops["S1"]))
    r2 = await api.get("/api/v1/amazon/orders", headers=auth(two_shops["S2"]))
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["shop_id"] == "S1"
    assert r2.json()["data"]["shop_id"] == "S2"


async def test_query_validation_returns_422(api, two_shops):
    r = await api.get("/api/v1/amazon/orders?limit=0", headers=auth(two_shops["S1"]))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_not_found_returns_404(api, two_shops):
    r = await api.get("/api/v1/amazon/products?asin=B0NOTEXIST", headers=auth(two_shops["S1"]))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_operations_shop_isolation(api, two_shops, sessionmaker_):
    from crossborder_ops.services import approval as svc

    op, _ = await svc.create_operation(
        sessionmaker_, shop_id="S1", agent_type="pricing", action_type="pricing.update_price",
        target_id="B0TEST0001", before={"price": 1.0}, after={"price": 2.0}, risk_level="low",
        created_by="t", idempotency_key=f"iso-{uuid.uuid4().hex}")
    r = await api.get(f"/api/v1/operations/{op['operation_id']}", headers=auth(two_shops["S2"]))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden_shop"
    ok = await api.get(f"/api/v1/operations/{op['operation_id']}", headers=auth(two_shops["S1"]))
    assert ok.status_code == 200


async def test_health_and_ready(api):
    assert (await api.get("/healthz")).json()["ok"] is True
    body = (await api.get("/readyz")).json()
    assert body["ok"] is True and body["checks"]["database"] == "ok"


async def test_metrics_endpoint(api):
    r = await api.get("/metrics")
    assert r.status_code == 200
    assert "crossborder_http_requests_total" in r.text
