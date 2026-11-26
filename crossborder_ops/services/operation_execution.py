"""审批执行：数据库目标写回 + 审计；非数据库目标走本地 Mock 适配器（明确标记来源）。

注意：local adapter 只用于演示/测试合成数据，响应里会标注 execution_target=mock，
不允许把 Mock 执行描述成真实平台操作。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core import audit as audit_core
from ..core.errors import NotFoundError
from ..core.security import ShopContext
from ..integrations.local.adapter import LocalDataAdapter
from ..repositories import business as repo
from ..services import approval as approval_service

SessionFactory = async_sessionmaker[AsyncSession]

DB_ACTIONS = {"product.update_listing", "pricing.update_price"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _DbProductAdapter:
    """把数据库商品行包装成执行器需要的同步适配器（读当前值 / 暂存修改）。"""

    def __init__(self, row: dict):
        self.row = row
        self.applied: dict | None = None

    def listing_snapshot(self, shop_id: str, target_id: str) -> dict:
        return {"title": self.row["title"], "status": self.row["status"]}

    def pricing_row(self, shop_id: str, target_id: str) -> dict:
        return {"price": float(self.row["price"])}

    def apply_listing(self, shop_id: str, target_id: str, after: dict) -> dict:
        self.applied = dict(after)
        return self.applied

    def apply_price(self, shop_id: str, target_id: str, price: float) -> dict:
        self.applied = {"price": price}
        return self.applied


async def _load_product(sm: SessionFactory, shop_id: str, sku: str) -> dict | None:
    async with sm() as session:
        async with session.begin():
            row = await repo.get_product(session, shop_id, sku)
            if row is None:
                return None
            return {"sku": row.sku, "title": row.title, "status": row.status,
                    "price": row.price}


async def _persist_product(sm: SessionFactory, shop_id: str, sku: str,
                           after: dict) -> dict | None:
    async with sm() as session:
        async with session.begin():
            row = await repo.get_product(session, shop_id, sku)
            if row is None:
                return None
            before = {"title": row.title, "status": row.status, "price": str(row.price)}
            for key, value in after.items():
                if key == "price":
                    setattr(row, key, Decimal(str(value)))
                else:
                    setattr(row, key, value)
            row.updated_at = _now()
            return {"before": before,
                    "after": {"title": row.title, "status": row.status,
                              "price": str(row.price)}}


async def execute(sm: SessionFactory, ctx: ShopContext, op_id: str,
                  request_id: str | None = None) -> dict:
    operation = await approval_service.get_operation(sm, op_id, shop_id=ctx.shop_id)
    action_type = operation["action_type"]
    target_id = operation["target_id"]
    after = operation["after_snapshot"] or {}
    agent_type = operation.get("agent_type", "product")

    db_row = await _load_product(sm, ctx.shop_id, target_id) if action_type in DB_ACTIONS else None
    target_kind = "db" if db_row is not None else "mock"
    data = _DbProductAdapter(db_row) if db_row is not None else LocalDataAdapter()

    result = await approval_service.execute_operation(sm, op_id, shop_id=ctx.shop_id,
                                                      data=data)
    persisted = None
    failure_reason = None
    if result == "executed" and db_row is not None:
        applied = getattr(data, "applied", None) or after
        persisted = await _persist_product(sm, ctx.shop_id, target_id, applied)
    elif result == "executed":
        persisted = {"mock_applied": after}
    else:
        failure_reason = result

    async with sm() as session:
        async with session.begin():
            detail = await approval_service.get_operation(sm, op_id, shop_id=ctx.shop_id)
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action="operation.execute",
                entity_type=agent_type or "operation", entity_id=target_id,
                before=(persisted or {}).get("before"),
                after=(persisted or {}).get("after") if persisted else None,
                request_id=request_id, operation_id=op_id,
                result="ok" if result == "executed" else "failed",
                failure_reason=failure_reason)
    return {"operation_id": op_id, "result": result, "operation": detail,
            "execution_target": target_kind,
            "persisted": persisted is not None}
