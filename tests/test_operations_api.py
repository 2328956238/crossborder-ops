# -*- coding: utf-8 -*-
"""审批 API 端到端：提交（DRAFT）→ 审批 → 执行 → 查询；重复执行跳过；无 token 401。"""
from __future__ import annotations

import uuid

from tests.conftest import auth


async def test_operation_api_end_to_end(api, two_shops):
    sku = f"E2E-{uuid.uuid4().hex[:6]}"
    created = await api.post("/api/v1/products", headers=auth(two_shops["S1"]),
                             json={"sku": sku, "title": "端到端商品", "price": 30.0})
    assert created.status_code == 201

    submitted = await api.post("/api/v1/operations", headers=auth(two_shops["operator"]),
                               json={"action_type": "pricing.update_price", "target_id": sku,
                                     "after": {"price": 28.0},
                                     "reason": "端到端测试",
                                     "idempotency_key": f"e2e-{uuid.uuid4().hex}"})
    assert submitted.status_code == 201
    op_id = submitted.json()["data"]["operation_id"]
    assert (await api.post(f"/api/v1/operations/{op_id}/submit",
                           headers=auth(two_shops["operator"]), json={})
            ).json()["data"]["result"] == "submitted"

    approved = await api.post(f"/api/v1/operations/{op_id}/approve",
                              headers=auth(two_shops["S1"]))
    assert approved.status_code == 200
    assert approved.json()["data"]["result"] == "approved"

    executed = await api.post(f"/api/v1/operations/{op_id}/execute",
                              headers=auth(two_shops["S1"]))
    assert executed.status_code == 200
    body = executed.json()["data"]
    assert body["result"] == "executed"
    assert body["operation"]["status"] == "EXECUTED"
    assert body["execution_target"] == "db"

    listed = await api.get("/api/v1/operations", headers=auth(two_shops["S1"]))
    assert listed.status_code == 200
    assert any(i["operation_id"] == op_id for i in listed.json()["data"]["items"])

    # 重复执行被跳过
    again = await api.post(f"/api/v1/operations/{op_id}/execute",
                           headers=auth(two_shops["S1"]))
    assert again.json()["data"]["result"] == "skipped"

    # 缺少 token → 401
    assert (await api.get("/api/v1/operations")).status_code == 401
