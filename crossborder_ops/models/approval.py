"""统一写操作审批模型：Operation 状态机 + 审计。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, DateTime, ForeignKey, Index, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Operation(Base):
    """一次待审批/已审批/已执行的写操作（商品、价格等）。

    状态机：PENDING_APPROVAL → APPROVED → EXECUTING → EXECUTED
                  ↘ REJECTED                  ↘ FAILED / UNKNOWN
    """

    __tablename__ = "operation"
    __table_args__ = (
        UniqueConstraint("shop_id", "idempotency_key", name="uq_operation_idem"),
        Index("ix_operation_shop_status", "shop_id", "status"),
        Index("ix_operation_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)      # uuid，同时是执行幂等键
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey("shops.id",
                                                                  ondelete="CASCADE"),
                                          nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class OperationAudit(Base):
    __tablename__ = "operation_audit"
    __table_args__ = (Index("ix_operation_audit_operation_id", "operation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), ForeignKey("operation.id",
                                                                    ondelete="CASCADE"),
                                              nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
