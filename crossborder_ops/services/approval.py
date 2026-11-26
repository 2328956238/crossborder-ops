"""审批与执行服务（独立业务能力，不依赖任何 Agent / LLM / 编排层）。

状态机：
    PENDING_APPROVAL → APPROVED → EXECUTING → EXECUTED
                    ↘ REJECTED              ↘ FAILED / UNKNOWN
约束：
- 执行前必须重新读取当前值并与 before_snapshot 比对（防覆盖别人修改）；
- 超时/网络类异常 = 结果未知（UNKNOWN），不重试、不自动回滚；
- 每次流转写 operation_audit。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.errors import ApprovalError
from ..models import Operation
from ..repositories import approval as repo
from .executors import EXECUTORS, is_unknown_error

PENDING = "PENDING_APPROVAL"
APPROVED = "APPROVED"
EXECUTING = "EXECUTING"
EXECUTED = "EXECUTED"
REJECTED = "REJECTED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
ROLLED_BACK = "ROLLED_BACK"

TERMINAL = {EXECUTED, REJECTED, FAILED, UNKNOWN, ROLLED_BACK}
ROLE_FOR_RISK = {"low": {"operator", "admin"}, "medium": {"operator", "admin"}, "high": {"admin"}}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

SessionFactory = async_sessionmaker[AsyncSession]


async def create_operation(sm: SessionFactory, *, shop_id: str, agent_type: str, action_type: str,
                           target_id: str, before: dict, after: dict, risk_level: str,
                           created_by: str, idempotency_key: str) -> tuple[dict, bool]:
    """创建待审批操作；同店同幂等键重复请求返回已有操作。"""
    if action_type not in EXECUTORS:
        raise ApprovalError("unknown_action", f"未登记的操作类型: {action_type}")
    if not shop_id or not target_id:
        raise ApprovalError("invalid_arg", "shop_id / target_id 不能为空")
    if risk_level not in RISK_ORDER:
        raise ApprovalError("invalid_arg", f"非法风险等级: {risk_level}")
    if not idempotency_key:
        raise ApprovalError("invalid_arg", "idempotency_key 不能为空")

    async with sm() as session, session.begin():
        existing = await repo.get_by_idempotency(session, shop_id, idempotency_key)
        if existing:
            return repo.to_dict(existing), False
        op = Operation(
            id=str(uuid.uuid4()), shop_id=shop_id, agent_type=agent_type,
            action_type=action_type, target_id=target_id,
            before_snapshot=before, after_snapshot=after,
            risk_level=risk_level, status=PENDING, idempotency_key=idempotency_key,
            created_by=created_by, approved_by=None, error_code=None,
            updated_at=repo.now_iso(),
        )
        session.add(op)
        repo.add_audit(session, op.id, "create", created_by, "ok",
                       f"{action_type} target={target_id} risk={risk_level}")
        return repo.to_dict(op), True


async def _load(sm: SessionFactory, op_id: str, shop_id: str | None = None) -> Operation:
    async with sm() as session:
        async with session.begin():
            op = await repo.get(session, op_id)
    if op is None:
        raise ApprovalError("not_found", "操作不存在")
    if shop_id is not None and op.shop_id != shop_id:
        raise ApprovalError("forbidden_shop", "操作不属于当前店铺")
    return op


async def approve_operation(sm: SessionFactory, op_id: str, *, shop_id: str,
                            actor: str, role: str) -> str:
    op = await _load(sm, op_id, shop_id)
    if op.status != PENDING:
        return "conflict"
    if role not in ROLE_FOR_RISK.get(op.risk_level, {"admin"}):
        async with sm() as session, session.begin():
            repo.add_audit(session, op_id, "approve", actor, "denied",
                           f"role={role} risk={op.risk_level}")
        return "forbidden"
    async with sm() as session, session.begin():
        won = await repo.transition(session, op_id, PENDING, APPROVED, approved_by=actor)
        repo.add_audit(session, op_id, "approve", actor, "ok" if won else "conflict")
    return "approved" if won else "conflict"


async def reject_operation(sm: SessionFactory, op_id: str, *, shop_id: str, actor: str) -> str:
    await _load(sm, op_id, shop_id)
    async with sm() as session, session.begin():
        won = await repo.transition(session, op_id, PENDING, REJECTED)
        repo.add_audit(session, op_id, "reject", actor, "ok" if won else "conflict")
    return "rejected" if won else "conflict"


async def execute_operation(sm: SessionFactory, op_id: str, *, shop_id: str, data: Any) -> str:
    """执行已审批操作。返回 executed / failed / unknown / skipped / stale。"""
    op = await _load(sm, op_id, shop_id)
    executor = EXECUTORS.get(op.action_type)
    if executor is None:
        raise ApprovalError("unknown_action", f"未登记的操作类型: {op.action_type}")

    async with sm() as session, session.begin():
        won = await repo.transition(session, op_id, APPROVED, EXECUTING)
        repo.add_audit(session, op_id, "execute_start", "system", "ok" if won else "conflict")
    if not won:
        return "skipped"

    try:
        current = executor.read_current(data, op.shop_id, op.target_id)
        problems = executor.validate(op.before_snapshot or {}, op.after_snapshot or {}, current)
        if problems:
            code = "stale_before_value" if any(p.startswith("stale") for p in problems) else "rule_violation"
            async with sm() as session, session.begin():
                await repo.transition(session, op_id, EXECUTING, FAILED, error_code=code)
                repo.add_audit(session, op_id, "execute_done", "system", "fail", ";".join(problems))
            return "stale" if code == "stale_before_value" else "failed"
        executor.apply(data, op.shop_id, op.target_id, op.after_snapshot or {})
    except Exception as exc:  # noqa: BLE001 - 执行边界必须兜住所有异常并分类
        if is_unknown_error(exc):
            async with sm() as session, session.begin():
                await repo.transition(session, op_id, EXECUTING, UNKNOWN,
                                      error_code="execution_result_unknown")
                repo.add_audit(session, op_id, "execute_unknown", "system", "unknown", repr(exc))
            return "unknown"
        code = getattr(exc, "code", type(exc).__name__.lower())
        async with sm() as session, session.begin():
            await repo.transition(session, op_id, EXECUTING, FAILED, error_code=str(code))
            repo.add_audit(session, op_id, "execute_done", "system", "fail", repr(exc))
        return "failed"

    async with sm() as session, session.begin():
        await repo.transition(session, op_id, EXECUTING, EXECUTED)
        repo.add_audit(session, op_id, "execute_done", "system", "ok", "applied to mock adapter")
    return "executed"


async def get_operation(sm: SessionFactory, op_id: str, *, shop_id: str) -> dict:
    op = await _load(sm, op_id, shop_id)
    async with sm() as session:
        async with session.begin():
            rows = await repo.list_audits(session, op_id)
    data = repo.to_dict(op)
    data["audit"] = [{"step": r.step, "actor": r.actor, "result": r.result,
                      "detail": r.detail, "at": r.created_at.isoformat() if r.created_at else None}
                     for r in rows]
    return data


async def list_operations(sm: SessionFactory, *, shop_id: str, status: str | None = None,
                          limit: int = 50) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ApprovalError("invalid_arg", "limit 必须在 1..200")
    async with sm() as session:
        async with session.begin():
            rows = await repo.list_by_shop(session, shop_id, status=status, limit=limit)
    return [repo.to_dict(r) for r in rows]
