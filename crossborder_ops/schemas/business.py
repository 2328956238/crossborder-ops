"""业务 Schema（Pydantic v2）：所有请求/响应模型集中在这里，路由不拼裸 dict。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- shops ----------------
class ShopCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    marketplace: str = Field(default="amazon", min_length=2, max_length=32)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class ShopOut(ORMModel):
    id: str
    name: str
    marketplace: str
    currency: str
    timezone: str
    status: str
    created_at: datetime | None = None


# ---------------- products ----------------
class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    asin: str | None = Field(default=None, max_length=20)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(active|inactive|archived)$")
    price: Decimal | None = Field(default=None, ge=0)


class ProductOut(ORMModel):
    id: str
    shop_id: str
    sku: str
    asin: str | None = None
    title: str
    status: str
    price: Decimal
    currency: str


# ---------------- orders ----------------
class OrderOut(ORMModel):
    id: int
    shop_id: str
    order_id: str
    status: str
    last_update_time: str
    version: int
    total_amount: Decimal
    currency: str
    channel: str | None = None


class OrderStats(BaseModel):
    days: int
    order_count: int
    revenue: Decimal
    by_status: dict[str, int]


# ---------------- inventory ----------------
class InventoryUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=64)
    warehouse: str = Field(default="default", max_length=32)
    on_hand: int = Field(ge=0)
    reserved: int = Field(default=0, ge=0)
    inbound: int = Field(default=0, ge=0)
    safety_stock: int = Field(default=0, ge=0)
    lead_time_days: int = Field(default=0, ge=0, le=365)


class InventoryAdjust(BaseModel):
    """只允许对已存在 SKU 调整；delta 可正可负（例如 -3 表示出库 3 件）。"""

    model_config = ConfigDict(extra="forbid")
    on_hand_delta: int = 0
    reserved_delta: int = 0
    inbound_delta: int = 0


class InventoryOut(ORMModel):
    id: int
    shop_id: str
    sku: str
    warehouse: str
    quantity: int
    on_hand: int
    reserved: int
    inbound: int
    safety_stock: int
    lead_time_days: int


class LowStockItem(BaseModel):
    sku: str
    available: int
    safety_stock: int
    shortage: int


# ---------------- advertising ----------------
class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    platform: str = Field(default="meta", pattern="^(meta|amazon)$")
    currency: str = Field(default="USD", min_length=3, max_length=3)


class InsightUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: str = Field(pattern="^(account|adset|ad)$")
    entity_external_id: str = Field(min_length=1, max_length=64)
    date: date
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    conversions: Decimal = Field(default=Decimal("0"), ge=0)
    revenue: Decimal = Field(default=Decimal("0"), ge=0)


class AdMetrics(BaseModel):
    spend: Decimal
    revenue: Decimal
    impressions: int
    clicks: int
    conversions: Decimal
    ctr: float | None = None
    cpc: float | None = None
    cpm: float | None = None
    cpa: float | None = None
    roas: float | None = None
    acos: float | None = None


# ---------------- ad_shield ----------------
class RuleHit(BaseModel):
    rule_code: str
    severity: str
    entity_type: str
    entity_id: str
    window_key: str
    detail: dict = {}


class RiskEventOut(ORMModel):
    id: str
    shop_id: str
    rule_code: str
    severity: str
    entity_type: str
    entity_id: str
    window_key: str
    status: str
    detail: dict
    detected_at: str


# ---------------- reports ----------------
class ReportRange(BaseModel):
    shop_id: str
    date_from: date
    date_to: date
