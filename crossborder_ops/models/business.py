"""库存 / 广告关键词日报。"""
from __future__ import annotations

from sqlalchemy import (Float, ForeignKey, Index, Integer, Numeric, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

_SHOP_FK = "shops.id"


class Inventory(Base):
    """库存口径：可售 = on_hand − reserved；inbound 不计入可售（在途）。"""

    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("shop_id", "sku", name="uq_inventory"),
                      Index("ix_inventory_shop_sku", "shop_id", "sku"))

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"),
                                         index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    # 兼容旧字段：quantity 表示“当前可售”
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inbound: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AdReport(Base):
    __tablename__ = "ad_report"
    __table_args__ = (UniqueConstraint("shop_id", "day", "keyword_id", name="uq_ad_report"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"),
                                         index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    keyword_id: Mapped[str] = mapped_column(String(64), nullable=False)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    spend: Mapped[float] = mapped_column(Float, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, nullable=False)
