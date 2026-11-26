"""广告域模型：账户 / Campaign / AdSet / Ad / 分日指标（Phase 3 由 Meta 同步写入）。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Date, DateTime, ForeignKey, Index, Integer, Numeric, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

_SHOP_FK = "shops.id"


class AdAccount(Base):
    __tablename__ = "ad_accounts"
    __table_args__ = (UniqueConstraint("shop_id", "platform", "external_id", name="uq_ad_account"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(16), default="meta", nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = (UniqueConstraint("account_id", "external_id", name="uq_campaign_external"),
                      Index("ix_campaign_shop_status", "shop_id", "status"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("ad_accounts.id",
                                                                  ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdSet(Base):
    __tablename__ = "ad_sets"
    __table_args__ = (UniqueConstraint("campaign_id", "external_id", name="uq_adset_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("ad_campaigns.id",
                                                                   ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class Ad(Base):
    __tablename__ = "ads"
    __table_args__ = (UniqueConstraint("adset_id", "external_id", name="uq_ad_external"),
                      Index("ix_ad_shop_status", "shop_id", "status"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    adset_id: Mapped[str] = mapped_column(String(36), ForeignKey("ad_sets.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)


class AdInsight(Base):
    """分日指标；level + entity_external_id 支持账户/广告组/广告三个粒度。"""

    __tablename__ = "ad_insights"
    __table_args__ = (
        UniqueConstraint("shop_id", "level", "entity_external_id", "date",
                         name="uq_insight_daily"),
        Index("ix_insight_shop_date", "shop_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(12), nullable=False)   # account / adset / ad
    entity_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    conversions: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"),
                                                 nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
