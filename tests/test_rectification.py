# -*- coding: utf-8 -*-
"""第一轮整改测试：权限矩阵、审批工作流、通用审计、Webhook 安全。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import date

from tests.conftest import auth

# ======================= 权限矩阵 =======================

VIEWER_WRITES = [
    ("POST", "/api/v1/products", {"sku": "V-1", "title": "x", "price": 1}),
    ("PATCH", "/api/v1/products/V-1", {"price": 2}),
    ("PUT", "/api/v1/inventory/V-1", {"sku": "V-1", "on_hand": 1}),
    ("POST", "/api/v1/inventory/V-1/adjust", {"on_hand_delta": 1}),
    ("POST", "/api/v1/advertising/accounts", {"external_id": "act_viewer", "name": "v"}),
    ("POST", "/api/v1/advertising/insights",
     {"level": "account", "entity_external_id": "a", "date": "2026-01-01"}),
    ("POST", "/api/v1/meta/sync", {"since": "2026-01-01", "until": "2026-01-02"}),
    ("POST", "/api/v1/shops", {"id": "S9", "name": "x"}),
    ("POST", "/api/v1/operations",
     {"action_type": "pricing.update_price", "target_id": "x", "after": {"price": 1},
      "idempotency_key": "viewer-key"}),
]


async def test_viewer_cannot_write_anything(api, two_shops):
    for method, path, payload in VIEWER_WRITES:
        response = await api.request(method, path, headers=auth(two_shops["viewer"]),
                                     json=payload)
        assert response.status_code == 403, f"{method} {path} 应拒绝 viewer，实际 {response.status_code}"


async def test_viewer_can_still_read(api, two_shops):
    for path in ("/api/v1/products", "/api/v1/inventory", "/api/v1/orders",
                 "/api/v1/reports/inventory-warnings", "/api/v1/operations"):
        response = await api.get(path, headers=auth(two_shops["viewer"]))
        assert response.status_code == 200, path
    assert (await api.get("/api/v1/ad-shield/risks",
                          headers=auth(two_shops["viewer"]))).status_code == 200


async def test_operator_can_do_low_risk_writes(api, two_shops):
    sku = f"OP-{uuid.uuid4().hex[:6]}"
    created = await api.post("/api/v1/products", headers=auth(two_shops["operator"]),
                             json={"sku": sku, "title": "operator 商品", "price": 9.9})
    assert created.status_code == 201
    put = await api.put(f"/api/v1/inventory/{sku}", headers=auth(two_shops["operator"]),
                        json={"sku": sku, "on_hand": 5})
    assert put.status_code == 200 and put.json()["data"]["on_hand"] == 5


async def test_operator_high_risk_approval_forbidden(api, two_shops):
    sku = f"HIGH-{uuid.uuid4().hex[:6]}"
    await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                   json={"sku": sku, "title": "高危", "price": 10})
    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                               json={"action_type": "pricing.update_price", "target_id": sku,
                                     "after": {"price": 8}, "risk_level": "high",
                                     "idempotency_key": f"high-{uuid.uuid4().hex}"})
    assert submitted.status_code == 201
    op_id = submitted.json()["data"]["operation_id"]
    await api.post(f"/api/v1/operations/{op_id}/submit", headers=auth(two_shops["operator"]),
                   json={})
    denied = await api.post(f"/api/v1/operations/{op_id}/approve",
                            headers=auth(two_shops["operator"]))
    assert denied.json()["data"]["result"] == "forbidden"
    ok = await api.post(f"/api/v1/operations/{op_id}/approve",
                        headers=auth(two_shops["S1"]))
    assert ok.json()["data"]["result"] == "approved"


# ======================= 审批工作流 =======================

async def _create_product(api, token, sku: str, price: float = 20.0) -> None:
    response = await api.post("/api/v1/products", headers=auth(token),
                              json={"sku": sku, "title": f"商品 {sku}", "price": price})
    assert response.status_code == 201


async def _product_price(api, token, sku: str) -> str:
    response = await api.get(f"/api/v1/products/{sku}", headers=auth(token))
    return response.json()["data"]["price"]


async def test_operation_create_submit_approve_execute_persists_to_db(api, two_shops):
    sku = f"WF-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["S1"], sku, price=20.0)

    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                               json={"action_type": "pricing.update_price", "target_id": sku,
                                     "after": {"price": 17.5},
                                     "reason": "促销调价",
                                     "idempotency_key": f"wf-{uuid.uuid4().hex}"})
    assert submitted.status_code == 201
    operation = submitted.json()["data"]
    assert operation["status"] == "DRAFT"
    # before 快照由服务端读取（当前 DB 价格），不是客户端传的
    assert operation["before_snapshot"]["price"] == "20.0000"
    # 审批前数据不变
    assert await _product_price(api, two_shops["S1"], sku) == "20.0000"

    op_id = operation["operation_id"]
    assert (await api.post(f"/api/v1/operations/{op_id}/submit",
                           headers=auth(two_shops["operator"]), json={})
            ).json()["data"]["result"] == "submitted"
    assert (await api.post(f"/api/v1/operations/{op_id}/approve",
                           headers=auth(two_shops["S1"]))
            ).json()["data"]["result"] == "approved"
    executed = await api.post(f"/api/v1/operations/{op_id}/execute",
                              headers=auth(two_shops["operator"]))
    body = executed.json()["data"]
    assert body["result"] == "executed"
    assert body["execution_target"] == "db"
    assert body["persisted"] is True
    assert await _product_price(api, two_shops["S1"], sku) == "17.5000"

    # 防重复审批 / 防重复执行
    assert (await api.post(f"/api/v1/operations/{op_id}/approve",
                           headers=auth(two_shops["S1"]))
            ).json()["data"]["result"] == "conflict"
    assert (await api.post(f"/api/v1/operations/{op_id}/execute",
                           headers=auth(two_shops["operator"]))
            ).json()["data"]["result"] == "skipped"


async def test_operation_idempotent_and_cross_shop(api, two_shops):
    sku = f"IDEM-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["S1"], sku)
    key = f"idem-{uuid.uuid4().hex}"
    payload = {"action_type": "product.update_listing", "target_id": sku,
               "after": {"title": "新标题"}, "idempotency_key": key}
    first = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                           json=payload)
    second = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                            json=payload)
    assert first.json()["data"]["operation_id"] == second.json()["data"]["operation_id"]

    op_id = first.json()["data"]["operation_id"]
    cross = await api.post(f"/api/v1/operations/{op_id}/submit",
                           headers=auth(two_shops["S2"]), json={})
    assert cross.status_code == 403

    # 目标不属于当前店铺 → 404
    foreign = await api.post("/api/v1/operations", headers=auth(two_shops["S2"]),
                             json={"action_type": "product.update_listing",
                                   "target_id": sku, "after": {"title": "x"},
                                   "idempotency_key": f"foreign-{uuid.uuid4().hex}"})
    assert foreign.status_code == 404


async def test_stale_operation_cannot_execute(api, two_shops):
    sku = f"STALE-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["S1"], sku, price=30.0)
    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                               json={"action_type": "pricing.update_price", "target_id": sku,
                                     "after": {"price": 25.0},
                                     "idempotency_key": f"stale-{uuid.uuid4().hex}"})
    op_id = submitted.json()["data"]["operation_id"]
    await api.post(f"/api/v1/operations/{op_id}/submit", headers=auth(two_shops["operator"]),
                   json={})
    await api.post(f"/api/v1/operations/{op_id}/approve", headers=auth(two_shops["S1"]))

    # 其他流程先改了价格 → 旧操作必须被判 stale
    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.repositories import business as repo

    async with get_sessionmaker()() as session:
        async with session.begin():
            row = await repo.get_product(session, "S1", sku)
            row.price = 28.0

    executed = await api.post(f"/api/v1/operations/{op_id}/execute",
                              headers=auth(two_shops["operator"]))
    assert executed.json()["data"]["result"] == "stale"
    detail = await api.get(f"/api/v1/operations/{op_id}", headers=auth(two_shops["S1"]))
    assert detail.json()["data"]["status"] == "FAILED"
    assert await _product_price(api, two_shops["S1"], sku) == "28.0000"


async def test_concurrent_approve_only_one_wins(api, two_shops):
    import asyncio

    sku = f"CONC-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["S1"], sku)
    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                               json={"action_type": "product.update_listing", "target_id": sku,
                                     "after": {"title": "并发"},
                                     "idempotency_key": f"conc-{uuid.uuid4().hex}"})
    op_id = submitted.json()["data"]["operation_id"]
    await api.post(f"/api/v1/operations/{op_id}/submit", headers=auth(two_shops["operator"]),
                   json={})
    results = await asyncio.gather(*[
        api.post(f"/api/v1/operations/{op_id}/approve", headers=auth(two_shops["S1"]))
        for _ in range(10)])
    outcomes = [r.json()["data"]["result"] for r in results]
    assert outcomes.count("approved") == 1
    assert outcomes.count("conflict") == 9


# ======================= 审计 =======================

async def test_write_operations_are_audited(api, two_shops):
    from sqlalchemy import select

    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import AuditLog

    sku = f"AUD-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["operator"], sku, price=12.0)
    await api.put(f"/api/v1/inventory/{sku}", headers=auth(two_shops["operator"]),
                  json={"sku": sku, "on_hand": 7})
    await api.post(f"/api/v1/inventory/{sku}/adjust", headers=auth(two_shops["operator"]),
                   json={"on_hand_delta": -2})

    async with get_sessionmaker()() as session:
        async with session.begin():
            rows = list((await session.execute(
                select(AuditLog).where(AuditLog.entity_id == sku)
                .order_by(AuditLog.id))).scalars().all())
    actions = [r.action for r in rows]
    assert "product.create" in actions
    assert "inventory.upsert" in actions and "inventory.adjust" in actions
    adjust = next(r for r in rows if r.action == "inventory.adjust")
    assert adjust.actor_role == "operator"
    assert adjust.before_data["on_hand"] == 7 and adjust.after_data["on_hand"] == 5
    assert adjust.request_id


async def test_operation_audit_links_operation_id(api, two_shops):
    from sqlalchemy import select

    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import AuditLog

    sku = f"AUDOP-{uuid.uuid4().hex[:6]}"
    await _create_product(api, two_shops["S1"], sku)
    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["S1"]),
                               json={"action_type": "product.update_listing", "target_id": sku,
                                     "after": {"title": "审计标题"},
                                     "idempotency_key": f"aud-{uuid.uuid4().hex}"})
    op_id = submitted.json()["data"]["operation_id"]
    await api.post(f"/api/v1/operations/{op_id}/submit", headers=auth(two_shops["S1"]), json={})
    await api.post(f"/api/v1/operations/{op_id}/approve", headers=auth(two_shops["S1"]))
    await api.post(f"/api/v1/operations/{op_id}/execute", headers=auth(two_shops["S1"]))

    async with get_sessionmaker()() as session:
        async with session.begin():
            rows = list((await session.execute(
                select(AuditLog).where(AuditLog.operation_id == op_id))).scalars().all())
    assert {"operation.create", "operation.submit", "operation.approve",
            "operation.execute"} <= {r.action for r in rows}
    execute_audit = next(r for r in rows if r.action == "operation.execute")
    assert execute_audit.result == "ok"
    assert execute_audit.before_data["title"] != execute_audit.after_data["title"]


async def test_audit_masks_tokens_and_records_failures(api, two_shops):
    from sqlalchemy import select

    from crossborder_ops.core import audit as audit_core
    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import AuditLog

    async with get_sessionmaker()() as session:
        async with session.begin():
            entry = await audit_core.record(
                session, shop_id="S1", actor="tester", role="admin",
                action="meta.oauth.exchange", entity_type="shop_credential",
                entity_id="meta", before=None,
                after={"access_token": "EAAG-super-secret-token-1234567890",
                       "refresh_token": "refresh-secret", "token_masked": "EAAG***oken"})
    async with get_sessionmaker()() as session:
        async with session.begin():
            row = await session.get(AuditLog, entry.id)
            dumped = json.dumps({"before": row.before_data, "after": row.after_data})
    assert "EAAG-super-secret" not in dumped
    assert "refresh-secret" not in dumped
    assert row.after_data["access_token"] == "***"

    # 失败写入也要留痕（重复创建商品 → 409 + failed 审计）
    sku = f"FAIL-{uuid.uuid4().hex[:6]}"
    await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                   json={"sku": sku, "title": "失败审计", "price": 1})
    duplicate = await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                               json={"sku": sku, "title": "重复", "price": 1})
    assert duplicate.status_code == 409
    async with get_sessionmaker()() as session:
        async with session.begin():
            failed = list((await session.execute(
                select(AuditLog).where(AuditLog.entity_id == sku,
                                       AuditLog.result == "failed"))).scalars().all())
    assert failed and "ConflictError" in (failed[-1].failure_reason or "")


# ======================= Webhook 安全 =======================

def _sign(secret: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    ts = ts or int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Timestamp": str(ts), "X-Signature": f"sha256={digest}",
            "Content-Type": "application/json"}


def _event(shop: str = "S1", event_id: str | None = None) -> dict:
    return {"shop_id": shop, "event_id": event_id or f"wh-{uuid.uuid4().hex}",
            "type": "ORDER_CHANGE", "event_time": "2026-05-01T00:00:00+00:00",
            "order_id": f"O-{uuid.uuid4().hex[:8]}", "status": "SHIPPED"}


async def test_webhook_signature_accepts_valid(api, monkeypatch):
    from crossborder_ops.config import get_settings

    secret = "test-webhook-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    try:
        body = json.dumps(_event()).encode()
        response = await api.post("/webhook/amazon", content=body, headers=_sign(secret, body))
        assert response.status_code == 200 and response.json()["status"] == "ok"
    finally:
        get_settings.cache_clear()


async def test_webhook_rejects_bad_signature_and_expired(api, monkeypatch):
    from crossborder_ops.config import get_settings

    secret = "test-webhook-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    try:
        body = json.dumps(_event()).encode()
        bad = _sign(secret, body)
        bad["X-Signature"] = "sha256=deadbeef"
        assert (await api.post("/webhook/amazon", content=body, headers=bad)).status_code == 401
        expired = _sign(secret, body, ts=int(time.time()) - 2000)
        response = await api.post("/webhook/amazon", content=body, headers=expired)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "webhook_timestamp_expired"
    finally:
        get_settings.cache_clear()


async def test_webhook_unknown_shop_rejected_without_auto_create(api, monkeypatch):
    from sqlalchemy import select

    from crossborder_ops.config import get_settings
    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import Shop

    secret = "test-webhook-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    try:
        body = json.dumps(_event(shop="S-UNKNOWN")).encode()
        response = await api.post("/webhook/amazon", content=body, headers=_sign(secret, body))
        assert response.status_code == 404
        async with get_sessionmaker()() as session:
            async with session.begin():
                shop = await session.get(Shop, "S-UNKNOWN")
        assert shop is None, "禁止通过 webhook 自动创建店铺"
    finally:
        get_settings.cache_clear()


async def test_webhook_replay_and_duplicate_not_reprocessed(api, monkeypatch):
    from sqlalchemy import func, select

    from crossborder_ops.config import get_settings
    from crossborder_ops.db import get_sessionmaker
    from crossborder_ops.models import PlatformEvent

    secret = "test-webhook-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    get_settings.cache_clear()
    try:
        event = _event()
        body = json.dumps(event).encode()
        headers = _sign(secret, body)
        first = await api.post("/webhook/amazon", content=body, headers=headers)
        second = await api.post("/webhook/amazon", content=body, headers=headers)
        assert first.json()["status"] == "ok"
        assert second.json()["status"] == "duplicate"
        async with get_sessionmaker()() as session:
            async with session.begin():
                count = (await session.execute(
                    select(func.count()).select_from(PlatformEvent)
                    .where(PlatformEvent.event_id == event["event_id"]))).scalar_one()
        assert count == 1
    finally:
        get_settings.cache_clear()


async def test_service_layer_rejects_viewer(sessionmaker_):
    """绕过 API 直接调 Service 也不能越权写入（Service 内 ensure_role）。"""
    from fastapi import HTTPException
    from pydantic import ValidationError as PydanticValidationError
    import pytest

    from crossborder_ops.core.security import ShopContext
    from crossborder_ops.schemas.business import ProductCreate
    from crossborder_ops.services import catalog, inventory

    viewer = ShopContext(shop_id="S1", actor="v", role="viewer", token_id="t")
    async with sessionmaker_() as session:
        with pytest.raises(HTTPException) as exc:
            await catalog.create_product(
                session, viewer,
                ProductCreate(sku="SVC-1", title="x", price=1))
        assert exc.value.status_code == 403

    operator = ShopContext(shop_id="S1", actor="op", role="operator", token_id="t")
    async with sessionmaker_() as session:
        with pytest.raises(HTTPException) as exc:
            await inventory.upsert(session, viewer, _inventory_payload("SVC-2"))
        assert exc.value.status_code == 403
        await inventory.upsert(session, operator, _inventory_payload("SVC-2"))


def _inventory_payload(sku: str):
    from crossborder_ops.schemas.business import InventoryUpsert

    return InventoryUpsert(sku=sku, on_hand=1)
