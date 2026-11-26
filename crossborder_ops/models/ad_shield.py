"""广告盾模型：审核状态 / 风险事件 / 告警（Phase 4 规则与巡检写入）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

_SHOP_FK = "shops.id"


class AdReview(Base):
    """广告审核状态快照；reason 拿不到时必须标记 manual_required。"""

    __tablename__ = "ad_reviews"
    __table_args__ = (UniqueConstraint("shop_id", "ad_id", "fetched_at", name="uq_ad_review"),
                      Index("ix_ad_review_shop_status", "shop_id", "status"))

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    # 存 Meta 侧外部广告 id（审核快照属于外部实体，不强制本地 ads 行存在）
    ad_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_required: Mapped[bool] = mapped_column(default=False, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String(40), nullable=False)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (UniqueConstraint("shop_id", "rule_code", "entity_type", "entity_id",
                                       "window_key", name="uq_risk_event"),
                      Index("ix_risk_event_shop_status", "shop_id", "status"))

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    rule_code: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)   # info/warn/critical
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)  # account/ad/...
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    window_key: Mapped[str] = mapped_column(String(16), nullable=False)   # 去重窗口，如 2026-01-10
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    detected_at: Mapped[str] = mapped_column(String(40), nullable=False)
    acked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_alert_dedupe"),
                      Index("ix_alert_shop_status", "shop_id", "status"))

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey(_SHOP_FK, ondelete="CASCADE"))
    risk_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("risk_events.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="log", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
