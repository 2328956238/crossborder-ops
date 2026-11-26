"""库存与广告日报（阶段 1 保留原表；阶段 2 扩展字段并接入 PG 仓储）。"""
from __future__ import annotations

from sqlalchemy import Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("shop_id", "sku", name="uq_inventory"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class AdReport(Base):
    __tablename__ = "ad_report"
    __table_args__ = (UniqueConstraint("shop_id", "day", "keyword_id", name="uq_ad_report"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    keyword_id: Mapped[str] = mapped_column(String(64), nullable=False)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    spend: Mapped[float] = mapped_column(Float, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, nullable=False)
