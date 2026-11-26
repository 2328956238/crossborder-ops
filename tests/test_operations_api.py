# -*- coding: utf-8 -*-
"""审批 API 端到端：创建（service）→ 审批 → 执行 → 审计查询。"""
from __future__ import annotations

import uuid

from tests.conftest import auth


async def test_operation_api_end_to_end(api, two_shops, sessionmaker_):
    from crossborder_ops.integrations.local.adapter import LocalDataAdapter
    from crossborder_ops.services import approval as svc

    data = LocalDataAdapter()
    current = data.pricing_row("S1", "B0TEST0001")
    op, _ = await svc.create_operation(
        sessionmaker_, shop_id="S1", agent_type="pricing", action_type="pricing.update_price",
        target_id="B0TEST0001", before={"price": current["price"]},
        after={"price": current["price"] + 1.0}, risk_level="low",
        created_by="tester", idempotency_key=f"api-{uuid.uuid4().hex}")

    op_id = op["operation_id"]
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

    listed = await api.get("/api/v1/operations", headers=auth(two_shops["S1"]))
    assert listed.status_code == 200
    assert any(i["operation_id"] == op_id for i in listed.json()["data"]["items"])

    # 重复执行被跳过
    again = await api.post(f"/api/v1/operations/{op_id}/execute",
                           headers=auth(two_shops["S1"]))
    assert again.json()["data"]["result"] == "skipped"

    # 缺少 token → 401
    assert (await api.get("/api/v1/operations")).status_code == 401
