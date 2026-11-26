# -*- coding: utf-8 -*-
"""审批状态机测试：生命周期 / 幂等 / 角色 / stale / UNKNOWN / 并发 / 跨店隔离。"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from crossborder_ops.core.errors import ApprovalError
from crossborder_ops.integrations.local.adapter import LocalDataAdapter
from crossborder_ops.services import approval as svc


def _key(prefix: str = "k") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _create(sm, *, action="pricing.update_price", target="B0TEST0001",
                  before=None, after=None, risk="low", shop="S1"):
    return await svc.create_operation(
        sm, shop_id=shop, agent_type="pricing", action_type=action, target_id=target,
        before=before or {"price": 0}, after=after or {"price": 1}, risk_level=risk,
        created_by="tester", idempotency_key=_key())


async def test_lifecycle_approve_execute(sessionmaker_):
    data = LocalDataAdapter()
    current = data.pricing_row("S1", "B0TEST0001")
    op, created = await _create(sessionmaker_, before={"price": current["price"]},
                                after={"price": 25.5})
    assert created and op["status"] == svc.PENDING

    assert await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                       actor="tester", role="admin") == "approved"
    assert await svc.execute_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                       data=data) == "executed"
    detail = await svc.get_operation(sessionmaker_, op["operation_id"], shop_id="S1")
    assert detail["status"] == svc.EXECUTED
    assert [a["step"] for a in detail["audit"]] == [
        "create", "approve", "execute_start", "execute_done"]
    # 执行后当前价已变
    assert abs(float(data.pricing_row("S1", "B0TEST0001")["price"]) - 25.5) < 1e-9


async def test_idempotent_create_returns_existing(sessionmaker_):
    key = _key()
    op1, created1 = await svc.create_operation(
        sessionmaker_, shop_id="S1", agent_type="pricing", action_type="pricing.update_price",
        target_id="B0TEST0001", before={"price": 1}, after={"price": 2}, risk_level="low",
        created_by="t", idempotency_key=key)
    op2, created2 = await svc.create_operation(
        sessionmaker_, shop_id="S1", agent_type="pricing", action_type="pricing.update_price",
        target_id="B0TEST0001", before={"price": 1}, after={"price": 2}, risk_level="low",
        created_by="t", idempotency_key=key)
    assert created1 is True and created2 is False
    assert op1["operation_id"] == op2["operation_id"]


async def test_unknown_action_rejected(sessionmaker_):
    with pytest.raises(ApprovalError) as exc:
        await _create(sessionmaker_, action="product.delete_everything")
    assert exc.value.code == "unknown_action"


async def test_high_risk_requires_admin(sessionmaker_):
    op, _ = await _create(sessionmaker_, risk="high")
    result = await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                         actor="op", role="operator")
    assert result == "forbidden"
    assert await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                       actor="admin", role="admin") == "approved"


async def test_stale_before_value_blocks_execution(sessionmaker_):
    op, _ = await _create(sessionmaker_, before={"price": 0.01}, after={"price": 22.0})
    await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                actor="a", role="admin")
    result = await svc.execute_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                         data=LocalDataAdapter())
    assert result == "stale"
    detail = await svc.get_operation(sessionmaker_, op["operation_id"], shop_id="S1")
    assert detail["status"] == svc.FAILED and detail["error_code"] == "stale_before_value"


async def test_unknown_outcome_not_retried(sessionmaker_, monkeypatch):
    data = LocalDataAdapter()
    current = data.pricing_row("S1", "B0TEST0001")
    op, _ = await _create(sessionmaker_, before={"price": current["price"]}, after={"price": 21.0})
    await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                actor="a", role="admin")

    class Boom:
        action_type = "pricing.update_price"

        def read_current(self, data, shop_id, target_id):
            return data.pricing_row(shop_id, target_id)

        def validate(self, before, after, current):
            return []

        def apply(self, data, shop_id, target_id, after):
            raise TimeoutError("upstream timeout")

    monkeypatch.setitem(svc.EXECUTORS, "pricing.update_price", Boom())
    assert await svc.execute_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                       data=data) == "unknown"
    detail = await svc.get_operation(sessionmaker_, op["operation_id"], shop_id="S1")
    assert detail["status"] == svc.UNKNOWN
    # 再次执行：UNKNOWN 是终态，不会被重新执行
    assert await svc.execute_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                                       data=data) == "skipped"


async def test_cross_shop_forbidden(sessionmaker_):
    op, _ = await _create(sessionmaker_, shop="S1")
    with pytest.raises(ApprovalError) as exc:
        await svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S2",
                                    actor="a", role="admin")
    assert exc.value.code == "forbidden_shop"


async def test_concurrent_approve_only_one_wins(sessionmaker_):
    op, _ = await _create(sessionmaker_)
    results = await asyncio.gather(*[
        svc.approve_operation(sessionmaker_, op["operation_id"], shop_id="S1",
                              actor=f"a{i}", role="admin") for i in range(20)])
    assert results.count("approved") == 1
    assert results.count("conflict") == 19
