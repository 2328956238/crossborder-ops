"""平台凭证（加密存储）：Meta 等平台的 access token。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ShopCredential(Base):
    __tablename__ = "shop_credentials"
    __table_args__ = (
        UniqueConstraint("shop_id", "provider", name="uq_shop_provider"),
        Index("ix_credential_shop_provider", "shop_id", "provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), ForeignKey("shops.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16), nullable=False)     # meta
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer", nullable=False)
    scopes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
