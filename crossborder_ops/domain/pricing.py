"""定价业务计算（Decimal 精度，纯函数，无 I/O）。

费用口径：单位成本 + 配送费 + 包装费 + 售价 × 佣金率。
利润按售价口径计算：profit = price × (1 - commission) - fixed_cost。
所有成本/费率都是 synthetic 假设，不代表 Amazon 真实收费标准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
Q4 = Decimal("0.0001")

ACTION_INCREASE = "increase_price"
ACTION_DECREASE = "decrease_price"
ACTION_MAINTAIN = "maintain_price"
ACTION_NEEDS_HUMAN = "needs_human"


class PricingError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def dec(value: Any) -> Decimal:
    """把数字/字符串转成 Decimal；拒绝 None 之外的空值。"""
    if value is None:
        raise PricingError("missing_fee_params", "缺少必要成本参数")
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise PricingError("invalid_arg", f"无法解析金额: {value!r}") from exc


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def rate(value: Decimal) -> Decimal:
    return value.quantize(Q4, ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeParams:
    unit_cost: Decimal
    commission_rate: Decimal
    shipping_fee: Decimal
    packaging_cost: Decimal
    target_margin: Decimal
    min_price: Decimal
    max_price: Decimal
    fee_source: str = "synthetic_assumption"

    @staticmethod
    def from_row(row: dict) -> "FeeParams":
        required = ("unit_cost", "commission_rate", "shipping_fee", "packaging_cost",
                    "target_margin", "min_price", "max_price")
        missing = [k for k in required if row.get(k) is None]
        if missing:
            raise PricingError("missing_fee_params", f"缺少成本参数: {', '.join(missing)}")
        p = FeeParams(
            unit_cost=dec(row["unit_cost"]), commission_rate=dec(row["commission_rate"]),
            shipping_fee=dec(row["shipping_fee"]), packaging_cost=dec(row["packaging_cost"]),
            target_margin=dec(row["target_margin"]), min_price=dec(row["min_price"]),
            max_price=dec(row["max_price"]), fee_source=row.get("fee_source", "synthetic_assumption"))
        if not (0 <= p.commission_rate < 1) or not (0 <= p.target_margin < 1):
            raise PricingError("invalid_arg", "佣金率/目标利润率必须在 [0,1)")
        if p.unit_cost < 0 or p.shipping_fee < 0 or p.packaging_cost < 0:
            raise PricingError("invalid_arg", "成本项不能为负")
        if p.min_price <= 0 or p.max_price < p.min_price:
            raise PricingError("invalid_arg", "价格边界不合法")
        if p.target_margin >= 1 - p.commission_rate:
            raise PricingError("invalid_arg", "目标利润率过高：售价无法覆盖佣金")
        return p

    @property
    def fixed_cost(self) -> Decimal:
        return self.unit_cost + self.shipping_fee + self.packaging_cost

    def breakeven_price(self) -> Decimal:
        """保本售价：利润 = 0 时的售价。"""
        return money(self.fixed_cost / (1 - self.commission_rate))

    def target_price(self) -> Decimal:
        """达到目标利润率所需售价（未做上下限裁剪）。"""
        return money(self.fixed_cost / (1 - self.commission_rate - self.target_margin))


@dataclass(frozen=True)
class PriceAnalysis:
    current_price: Decimal
    competitor_price: Decimal | None
    params: FeeParams
    fixed_cost: Decimal
    unit_profit: Decimal
    margin_rate: Decimal
    breakeven_price: Decimal
    target_price: Decimal
    recommended_price: Decimal
    action: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        def s(v: Decimal | None) -> str | None:
            return None if v is None else str(money(v))

        return {
            "currency": "USD",
            "current_price": str(money(self.current_price)),
            "competitor_price": s(self.competitor_price),
            "cost": {
                "unit_cost": str(money(self.params.unit_cost)),
                "shipping_fee": str(money(self.params.shipping_fee)),
                "packaging_cost": str(money(self.params.packaging_cost)),
                "commission_rate": str(rate(self.params.commission_rate)),
                "fixed_cost": str(money(self.fixed_cost)),
                "fee_source": self.params.fee_source,
                "declaration": "成本与费率为 synthetic 假设，不代表 Amazon 真实收费标准",
            },
            "profit": {
                "unit_profit": str(money(self.unit_profit)),
                "margin_rate": str(rate(self.margin_rate)),
                "target_margin": str(rate(self.params.target_margin)),
            },
            "prices": {
                "breakeven_price": str(money(self.breakeven_price)),
                "target_price": str(money(self.target_price)),
                "min_price": str(money(self.params.min_price)),
                "max_price": str(money(self.params.max_price)),
                "recommended_price": str(money(self.recommended_price)),
            },
            "decision": {"action": self.action, "reasons": list(self.reasons),
                         "warnings": list(self.warnings)},
            "formula": "profit = price*(1-commission) - (unit_cost+shipping+packaging); "
                       "breakeven = fixed/(1-commission); target = fixed/(1-commission-target_margin)",
        }


def analyze_price(current_price: float | str | Decimal,
                  competitor_price: float | str | Decimal | None,
                  params: FeeParams) -> PriceAnalysis:
    """生成价格分析与建议（纯计算，不写平台）。"""
    current = money(dec(current_price))
    competitor = money(dec(competitor_price)) if competitor_price is not None else None
    if current <= 0:
        raise PricingError("invalid_arg", "当前售价必须为正")

    fixed = params.fixed_cost
    profit = money(current * (1 - params.commission_rate) - fixed)
    margin = rate(profit / current) if current else Decimal(0)
    breakeven, target = params.breakeven_price(), params.target_price()

    reasons: list[str] = []
    warnings: list[str] = []
    recommended = current

    if current < params.min_price:
        action = ACTION_NEEDS_HUMAN
        reasons.append(f"当前价 {current} 低于允许最低价 {params.min_price}")
        warnings.append("低于价格下限，需人工确认（可能涉及促销或清仓策略）")
        recommended = params.min_price
    elif current > params.max_price:
        action = ACTION_NEEDS_HUMAN
        reasons.append(f"当前价 {current} 高于允许最高价 {params.max_price}")
        warnings.append("高于价格上限，需人工确认")
        recommended = params.max_price
    elif profit < 0:
        reasons.append(f"单位利润为负（{profit}），售价低于保本价 {breakeven}")
        recommended = max(target, params.min_price)
        action = ACTION_INCREASE
    elif margin < params.target_margin:
        action = ACTION_INCREASE
        reasons.append(f"利润率 {margin} 低于目标 {params.target_margin}")
        recommended = target
    elif competitor is not None and current > competitor * Decimal("1.10") \
            and margin > params.target_margin + Decimal("0.10"):
        action = ACTION_DECREASE
        reasons.append(f"售价高于竞品 10% 以上（{current} vs {competitor}）且利润充足")
        recommended = max(competitor, target, params.min_price)
    else:
        action = ACTION_MAINTAIN
        reasons.append("价格处于合理区间，维持当前售价")

    if competitor is not None:
        diff = (current - competitor) / competitor
        if diff > Decimal("0.20"):
            warnings.append(f"高于竞品 {diff:.1%}，可能影响 Buy Box")
        elif diff < Decimal("-0.20"):
            warnings.append(f"低于竞品 {abs(diff):.1%}，注意利润与品牌定位")
    if not params.min_price <= recommended <= params.max_price:
        warnings.append("建议价超出允许区间，已裁剪到边界")
        recommended = min(max(recommended, params.min_price), params.max_price)
        if action == ACTION_INCREASE and recommended < target:
            action = ACTION_NEEDS_HUMAN
            warnings.append("目标价超出上限，需人工确认")

    return PriceAnalysis(current_price=current, competitor_price=competitor, params=params,
                         fixed_cost=fixed, unit_profit=profit, margin_rate=margin,
                         breakeven_price=breakeven, target_price=target,
                         recommended_price=money(recommended), action=action,
                         reasons=tuple(reasons), warnings=tuple(warnings))
