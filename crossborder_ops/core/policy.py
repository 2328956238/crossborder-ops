"""操作风险策略（独立配置，不散落在路由里）。

- low    ：operator 可直接执行，必须审计；
- medium ：必须提交审批（operator 提交，operator/admin 审批）；
- high   ：必须提交审批，且只有 admin 能审批；
- admin  ：管理动作，仅 admin 直接执行（不进入审批，例如建店铺）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
RISK_ROLES = {
    "low": {"operator", "admin"},
    "medium": {"operator", "admin"},
    "high": {"admin"},
}


@dataclass(frozen=True)
class ActionPolicy:
    action_type: str
    entity_type: str
    risk: str
    requires_approval: bool
    fields: tuple[str, ...]
    description: str


POLICIES: dict[str, ActionPolicy] = {
    "product.create": ActionPolicy(
        "product.create", "product", "low", False,
        ("sku", "title", "asin", "price", "currency"), "创建商品"),
    "product.update_listing": ActionPolicy(
        "product.update_listing", "product", "medium", True,
        ("title", "status"), "修改 Listing 内容/状态（medium，需审批）"),
    "pricing.update_price": ActionPolicy(
        "pricing.update_price", "product", "medium", True,
        ("price",), "修改售价（medium，需审批）"),
    "inventory.upsert": ActionPolicy(
        "inventory.upsert", "inventory", "low", False,
        ("warehouse", "on_hand", "reserved", "inbound", "safety_stock", "lead_time_days"),
        "库存覆盖写入"),
    "inventory.adjust": ActionPolicy(
        "inventory.adjust", "inventory", "low", False,
        ("on_hand_delta", "reserved_delta", "inbound_delta"), "库存增量调整"),
    "advertising.account.create": ActionPolicy(
        "advertising.account.create", "ad_account", "low", False,
        ("external_id", "name", "platform", "currency"), "登记广告账户"),
    "advertising.insight.upsert": ActionPolicy(
        "advertising.insight.upsert", "ad_insight", "low", False,
        ("level", "entity_external_id", "date", "impressions", "clicks", "spend",
         "conversions", "revenue"), "写入广告分日指标"),
    "meta.sync": ActionPolicy(
        "meta.sync", "meta", "low", False, ("since", "until"), "触发 Meta 数据同步"),
    "ad_shield.risk.ack": ActionPolicy(
        "ad_shield.risk.ack", "risk_event", "low", False, ("status",), "确认风险事件"),
    "ad_shield.risk.resolve": ActionPolicy(
        "ad_shield.risk.resolve", "risk_event", "low", False, ("status",), "解决风险事件"),
    "shop.create": ActionPolicy(
        "shop.create", "shop", "admin", False, ("id", "name", "marketplace", "currency",
                                                "timezone"), "创建店铺（仅 admin）"),
}


def get_policy(action_type: str) -> ActionPolicy:
    policy = POLICIES.get(action_type)
    if policy is None:
        raise ValidationError(f"未登记的操作类型: {action_type}",
                              code="unknown_action")
    return policy


def effective_risk(action_type: str, client_risk: str | None = None) -> str:
    """客户端可声明更高风险，但不能把服务端风险降级。"""
    policy = get_policy(action_type)
    if client_risk is None:
        return policy.risk
    if client_risk not in RISK_ORDER:
        raise ValidationError(f"非法风险等级: {client_risk}")
    return client_risk if RISK_ORDER[client_risk] > RISK_ORDER[policy.risk] else policy.risk
