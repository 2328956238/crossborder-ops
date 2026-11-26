"""Operation 持久化：所有 SQL/ORM 访问集中在这里，service 不直接碰数据库。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Operation, OperationAudit


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get(session: AsyncSession, op_id: str) -> Operation | None:
    return (await session.execute(select(Operation).where(Operation.id == op_id))).scalar_one_or_none()


async def get_by_idempotency(session: AsyncSession, shop_id: str,
                             idempotency_key: str) -> Operation | None:
    return (await session.execute(select(Operation).where(
        Operation.shop_id == shop_id,
        Operation.idempotency_key == idempotency_key,
    ))).scalar_one_or_none()


async def list_by_shop(session: AsyncSession, shop_id: str, status: str | None = None,
                       limit: int = 50) -> list[Operation]:
    q = select(Operation).where(Operation.shop_id == shop_id)
    if status:
        q = q.where(Operation.status == status)
    q = q.order_by(Operation.created_at.desc()).limit(limit)
    return list((await session.execute(q)).scalars().all())


async def transition(session: AsyncSession, op_id: str, frm: str, to: str, **extra: Any) -> bool:
    """条件 UPDATE 抢锁：只有当前状态等于 frm 时才能流转（并发下只有一个赢家）。"""
    values = {"status": to, "updated_at": now_iso(), **extra}
    sets = ", ".join(f"{k} = :{k}" for k in values)
    result = await session.execute(
        text(f"UPDATE operation SET {sets} WHERE id = :id AND status = :frm"),
        {**values, "id": op_id, "frm": frm},
    )
    return result.rowcount == 1


def add_audit(session: AsyncSession, op_id: str, step: str, actor: str, result: str,
              detail: str = "") -> None:
    session.add(OperationAudit(operation_id=op_id, step=step, actor=actor,
                               result=result, detail=detail[:2000]))


async def list_audits(session: AsyncSession, op_id: str) -> list[OperationAudit]:
    return list((await session.execute(
        select(OperationAudit).where(OperationAudit.operation_id == op_id)
        .order_by(OperationAudit.id))).scalars().all())


def to_dict(op: Operation) -> dict[str, Any]:
    return {
        "operation_id": op.id, "shop_id": op.shop_id, "agent_type": op.agent_type,
        "action_type": op.action_type, "target_id": op.target_id,
        "before_snapshot": op.before_snapshot, "after_snapshot": op.after_snapshot,
        "risk_level": op.risk_level, "status": op.status,
        "idempotency_key": op.idempotency_key, "created_by": op.created_by,
        "approved_by": op.approved_by, "error_code": op.error_code,
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "updated_at": op.updated_at,
    }
