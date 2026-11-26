"""平台事件（webhook 去重）与订单同步模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PlatformEvent(Base):
    __tablename__ = "platform_event"
    __table_args__ = (UniqueConstraint("shop_id", "event_id", name="uq_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)   # 原始 JSON 文本，便于审计
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("shop_id", "order_id", name="uq_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 平台事件时间：只保存 UTC ISO-8601，字典序即时间序（阶段 2 迁移为 timestamptz）
    last_update_time: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SyncCursor(Base):
    """补拉水位线：只在本批全部写入成功后、同事务推进。"""

    __tablename__ = "sync_cursor"
    __table_args__ = (UniqueConstraint("shop_id", "name", name="uq_cursor"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(40), nullable=False)
