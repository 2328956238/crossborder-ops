"""审批提交：服务端读取目标当前快照，创建 DRAFT 操作（不直接改业务数据）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core import audit as audit_core
from ..core.errors import NotFoundError, ValidationError
from ..core.permissions import ensure_role
from ..core.policy import effective_risk, get_policy
from ..core.security import ShopContext
from ..repositories import ads as ads_repo
from ..repositories import business as repo
from ..repositories import approval as op_repo
from ..models import Operation

SessionFactory = async_sessionmaker[AsyncSession]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load_target(session: AsyncSession, shop_id: str, entity_type: str,
                       target_id: str) -> dict:
    """从数据库读取目标当前状态；不存在/不属于本店 → 404。"""
    if entity_type == "product":
        row = await repo.get_product(session, shop_id, target_id)
        if row is None:
            raise NotFoundError(f"商品不存在或不属于当前店铺: {target_id}")
        return {"id": row.id, "sku": row.sku, "title": row.title,
                "status": row.status, "price": str(row.price), "currency": row.currency}
    if entity_type == "inventory":
        row = await repo.get_inventory(session, shop_id, target_id)
        if row is None:
            raise NotFoundError(f"库存记录不存在或不属于当前店铺: {target_id}")
        return {"sku": row.sku, "warehouse": row.warehouse, "on_hand": row.on_hand,
                "reserved": row.reserved, "inbound": row.inbound,
                "safety_stock": row.safety_stock}
    if entity_type == "ad_account":
        accounts = await ads_repo.list_accounts(session, shop_id)
        for account in accounts:
            if account.id == target_id or account.external_id == target_id:
                return {"id": account.id, "external_id": account.external_id,
                        "name": account.name, "status": account.status}
        raise NotFoundError(f"广告账户不存在或不属于当前店铺: {target_id}")
    raise ValidationError(f"不支持的实体类型: {entity_type}")


def _validate_after(policy, after: dict) -> dict:
    if not isinstance(after, dict) or not after:
        raise ValidationError("after 不能为空")
    unknown = set(after) - set(policy.fields)
    if unknown:
        raise ValidationError(f"不支持的修改字段: {', '.join(sorted(unknown))}")
    cleaned = {}
    for key, value in after.items():
        if key == "price":
            try:
                price = float(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError("price 必须是数字") from exc
            if price <= 0:
                raise ValidationError("price 必须大于 0")
            cleaned[key] = float(value)
        elif key in {"title", "status"}:
            if not str(value or "").strip():
                raise ValidationError(f"{key} 不能为空")
            cleaned[key] = value
        else:
            cleaned[key] = value
    return cleaned


async def create_submission(sm: SessionFactory, ctx: ShopContext, payload,
                            request_id: str | None = None) -> dict:
    """创建待审批操作（DRAFT），before 由服务端读取。"""
    ensure_role(ctx, "operator", "admin")
    policy = get_policy(payload.action_type)
    if not policy.requires_approval:
        raise ValidationError(
            f"动作 {payload.action_type} 风险较低，可直接执行（已审计），无需审批",
            code="approval_not_required")
    risk = effective_risk(payload.action_type, payload.risk_level)
    after = _validate_after(policy, payload.after)

    async with sm() as session:
        async with session.begin():
            target = await _load_target(session, ctx.shop_id, policy.entity_type,
                                        payload.target_id)
            existing = await op_repo.get_by_idempotency(session, ctx.shop_id,
                                                        payload.idempotency_key)
            if existing:
                return op_repo.to_dict(existing)
            op = Operation(
                id=str(uuid.uuid4()), shop_id=ctx.shop_id, agent_type=policy.entity_type,
                action_type=payload.action_type, target_id=payload.target_id,
                before_snapshot=target, after_snapshot=after, risk_level=risk,
                status="DRAFT", idempotency_key=payload.idempotency_key,
                created_by=ctx.actor, approved_by=None, error_code=None,
                reason=payload.reason, updated_at=_now(),
            )
            session.add(op)
            op_repo.add_audit(session, op.id, "create", ctx.actor, "ok",
                              f"{payload.action_type} target={payload.target_id} risk={risk}")
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action="operation.create", entity_type="operation", entity_id=op.id,
                before=None,
                after={"action_type": payload.action_type, "target_id": payload.target_id,
                       "risk_level": risk, "status": "DRAFT"},
                request_id=request_id, operation_id=op.id)
            await session.flush()
            return op_repo.to_dict(op)


async def submit_operation(sm: SessionFactory, ctx: ShopContext, op_id: str,
                           request_id: str | None = None) -> dict:
    ensure_role(ctx, "operator", "admin")
    from . import approval as approval_service

    result = await approval_service.submit_operation(sm, op_id, shop_id=ctx.shop_id,
                                                     actor=ctx.actor)
    async with sm() as session:
        async with session.begin():
            op_repo.add_audit(session, op_id, "submit", ctx.actor,
                              "ok" if result == "submitted" else result)
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action="operation.submit", entity_type="operation", entity_id=op_id,
                before={"status": "DRAFT"},
                after={"status": "PENDING_APPROVAL" if result == "submitted" else result},
                request_id=request_id, operation_id=op_id,
                result="ok" if result == "submitted" else "failed",
                failure_reason=None if result == "submitted" else result)
    return {"operation_id": op_id, "result": result}


async def ensure_target_exists(sm: SessionFactory, ctx: ShopContext, operation: dict) -> None:
    """审批前重新校验：目标对象必须仍存在且属于当前店铺。"""
    async with sm() as session:
        async with session.begin():
            await _load_target(session, ctx.shop_id, operation.get("agent_type", ""),
                               operation["target_id"])
