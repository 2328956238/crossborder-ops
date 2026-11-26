"""平台事件 / 订单 / 水位线模型。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

_SHOP_FK = "shops.id"


class PlatformEvent(Base):
    __tablename__ = "platform_event"
    __table_args__ = (UniqueConstraint("shop_id", "event_id", name="uq_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"),
                                         index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("shop_id", "order_id", name="uq_order"),
                      Index("ix_order_shop_status", "shop_id", "status"))

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"),
                                         index=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_update_time: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Phase 2 新增经营字段
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"),
                                                  server_default="0", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD",
                                         server_default="USD", nullable=False)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class SyncCursor(Base):
    """补拉水位线：只在本批全部写入成功后、同事务推进。"""

    __tablename__ = "sync_cursor"
    __table_args__ = (UniqueConstraint("shop_id", "name", name="uq_cursor"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"),
                                         index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(40), nullable=False)
