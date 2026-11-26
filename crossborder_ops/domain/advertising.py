"""广告指标计算与阈值判断（Domain Service）。

设计约束：
1. 纯 Python 函数：不 import 数据库、Redis、LLM、任何 I/O。
2. 分母缺失（None 或 0）时返回 None，不抛异常；非法输入（负数、NaN、inf）抛 ValueError。
3. 返回值全部是冻结的 dataclass，可以直接序列化进 API 响应。
4. 这里的阈值是"业务口径"，和 agent/approval.py 里的"写操作规则"是两回事：
   - 本模块判断「这个广告表现好不好」；
   - approval.py 判断「这次改价能不能执行」。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _check_finite(name: str, value: float | None) -> None:
    """负数、NaN、inf 视为非法参数；None 表示"没有这个数据"，另行处理。"""
    if value is None:
        return
    if not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got bool")
    if math.isnan(float(value)) or math.isinf(float(value)):
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """安全除法：任一为空或分母为 0 时返回 None（表示"算不出来"，而不是 0）。"""
    _check_finite("numerator", numerator)
    _check_finite("denominator", denominator)
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------
def acos(spend: float | None, sales: float | None) -> float | None:
    """ACOS = 广告花费 / 广告销售额。返回小数（0.25 表示 25%）。"""
    return safe_div(spend, sales)


def roas(sales: float | None, spend: float | None) -> float | None:
    """ROAS = 广告销售额 / 广告花费（倍数，不是百分比）。"""
    return safe_div(sales, spend)


def ctr(clicks: int | None, impressions: int | None) -> float | None:
    """CTR = 点击 / 曝光。"""
    return safe_div(clicks, impressions)


def cvr(orders: int | None, clicks: int | None) -> float | None:
    """CVR = 订单 / 点击。"""
    return safe_div(orders, clicks)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdMetrics:
    """一次广告表现的结构化结果。算不出来的指标为 None，并在 missing 里注明原因。"""

    spend: float
    clicks: int
    orders: int
    impressions: int | None = None
    sales: float | None = None
    acos: float | None = None
    roas: float | None = None
    ctr: float | None = None
    cvr: float | None = None
    missing: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spend": self.spend,
            "clicks": self.clicks,
            "orders": self.orders,
            "impressions": self.impressions,
            "sales": self.sales,
            "acos": None if self.acos is None else round(self.acos, 6),
            "roas": None if self.roas is None else round(self.roas, 4),
            "ctr": None if self.ctr is None else round(self.ctr, 6),
            "cvr": None if self.cvr is None else round(self.cvr, 6),
            "missing": list(self.missing),
        }


def compute_metrics(
    spend: float | None,
    clicks: int | None,
    orders: int | None,
    impressions: int | None = None,
    sales: float | None = None,
) -> AdMetrics:
    """把一组原始广告数据算成指标。

    spend / clicks / orders 缺失时按 0 处理（它们是一手事实，缺了就是没有），
    但会在 missing 里标记出来；impressions / sales 缺失只影响 CTR / ACOS / ROAS。
    """
    _check_finite("spend", spend)
    _check_finite("clicks", clicks)
    _check_finite("orders", orders)
    _check_finite("impressions", impressions)
    _check_finite("sales", sales)

    missing: list[str] = []
    spend_v = 0.0 if spend is None else float(spend)
    clicks_v = 0 if clicks is None else int(clicks)
    orders_v = 0 if orders is None else int(orders)
    if spend is None:
        missing.append("spend")
    if clicks is None:
        missing.append("clicks")
    if orders is None:
        missing.append("orders")
    if impressions is None:
        missing.append("impressions")
    if sales is None:
        missing.append("sales")

    m = AdMetrics(
        spend=spend_v,
        clicks=clicks_v,
        orders=orders_v,
        impressions=impressions,
        sales=sales,
        acos=acos(spend_v, sales),
        roas=roas(sales, spend_v),
        ctr=ctr(clicks_v, impressions),
        cvr=cvr(orders_v, clicks_v),
        missing=tuple(missing),
    )
    return m


# ---------------------------------------------------------------------------
# 阈值判断
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AdThresholds:
    """业务阈值。默认值是常见跨境电商经验值，可按店铺配置，但不写死在计算里。"""

    acos_warn: float = 0.30
    acos_critical: float = 0.50
    roas_warn: float = 3.0
    roas_critical: float = 2.0
    ctr_warn: float = 0.004
    cvr_warn: float = 0.02
    min_clicks_for_judgement: int = 20


LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_CRITICAL = "critical"
LEVEL_INSUFFICIENT = "insufficient_data"


@dataclass(frozen=True)
class AdAssessment:
    """阈值判断结果。level 只有四种，reasons 是可解释的原因列表。"""

    level: str
    reasons: tuple[str, ...]
    metrics: AdMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "reasons": list(self.reasons),
            "metrics": self.metrics.to_dict(),
        }


def assess(metrics: AdMetrics, thresholds: AdThresholds | None = None) -> AdAssessment:
    """判断广告表现等级。

    规则：
    - 点击量不足 min_clicks_for_judgement：insufficient_data（不在小样本上下结论）
    - ACOS >= critical 或 ROAS <= critical：critical
    - ACOS >= warn 或 ROAS <= warn 或 CTR < ctr_warn 或 CVR < cvr_warn：warn
    - 其余：ok
    算不出来的指标（None）不参与判断，避免"没数据被当成正常"。
    """
    t = thresholds or AdThresholds()
    if metrics.clicks < t.min_clicks_for_judgement:
        return AdAssessment(
            LEVEL_INSUFFICIENT,
            (f"clicks {metrics.clicks} < {t.min_clicks_for_judgement}",),
            metrics,
        )

    critical: list[str] = []
    warn: list[str] = []

    if metrics.acos is not None:
        if metrics.acos >= t.acos_critical:
            critical.append(f"acos {metrics.acos:.2%} >= {t.acos_critical:.2%}")
        elif metrics.acos >= t.acos_warn:
            warn.append(f"acos {metrics.acos:.2%} >= {t.acos_warn:.2%}")
    if metrics.roas is not None:
        if metrics.roas <= t.roas_critical:
            critical.append(f"roas {metrics.roas:.2f} <= {t.roas_critical:.2f}")
        elif metrics.roas <= t.roas_warn:
            warn.append(f"roas {metrics.roas:.2f} <= {t.roas_warn:.2f}")
    if metrics.ctr is not None and metrics.ctr < t.ctr_warn:
        warn.append(f"ctr {metrics.ctr:.4%} < {t.ctr_warn:.4%}")
    if metrics.cvr is not None and metrics.cvr < t.cvr_warn:
        warn.append(f"cvr {metrics.cvr:.2%} < {t.cvr_warn:.2%}")

    if critical:
        return AdAssessment(LEVEL_CRITICAL, tuple(critical + warn), metrics)
    if warn:
        return AdAssessment(LEVEL_WARN, tuple(warn), metrics)
    return AdAssessment(LEVEL_OK, (), metrics)
