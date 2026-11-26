"""库存分析：可售口径、覆盖天数、风险分级、补货建议（纯函数，无 I/O）。

口径（与 FBA 业务一致）：
- available = on_hand - reserved                （当前真正可售）
- inbound **不计入**当前可售，只影响"在途到货后"的覆盖
- 日均销量 = 窗口内非取消订单销量 / 窗口天数
- Days of Cover = available / 日均销量
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from typing import Any

LEVEL_CRITICAL = "critical"
LEVEL_WARN = "warn"
LEVEL_OK = "ok"
LEVEL_NO_SALES = "no_sales"
LEVEL_SLOW_MOVING = "slow_moving"


@dataclass(frozen=True)
class InventoryParams:
    lead_time_days: int
    target_cover_days: int
    safety_stock: int
    moq: int

    @staticmethod
    def from_row(row: dict) -> "InventoryParams":
        def geti(key: str, default: int) -> int:
            v = row.get(key, default)
            try:
                return int(v)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} 非法: {v!r}") from exc

        p = InventoryParams(lead_time_days=geti("lead_time_days", 14),
                            target_cover_days=geti("target_cover_days", 30),
                            safety_stock=geti("safety_stock", 10),
                            moq=geti("moq", 1))
        if min(p.lead_time_days, p.target_cover_days, p.moq) <= 0 or p.safety_stock < 0:
            raise ValueError("补货参数必须为正（safety_stock 可为 0）")
        return p


@dataclass(frozen=True)
class InventoryAnalysis:
    sku: str
    asin: str
    on_hand: int
    reserved: int
    available: int
    inbound: int
    window_days: int
    sold_units: int
    daily_sales: Decimal
    days_of_cover: Decimal | None
    level: str
    recommended_qty: int
    reasons: tuple[str, ...] = field(default_factory=tuple)
    formula: str = ""

    def to_dict(self) -> dict[str, Any]:
        def q(v: Decimal | None) -> str | None:
            return None if v is None else str(v.quantize(Decimal("0.01")))

        return {
            "sku": self.sku, "asin": self.asin,
            "stock": {"on_hand": self.on_hand, "reserved": self.reserved,
                      "available": self.available, "inbound": self.inbound},
            "sales": {"window_days": self.window_days, "units": self.sold_units,
                      "daily_sales": q(self.daily_sales)},
            "days_of_cover": q(self.days_of_cover),
            "level": self.level,
            "replenishment": {"recommended_qty": self.recommended_qty,
                              "formula": self.formula},
            "reasons": list(self.reasons),
            "source": "synthetic",
        }


def analyze_inventory(row: dict, sold_units: int, window_days: int,
                      params: InventoryParams) -> InventoryAnalysis:
    if window_days <= 0:
        raise ValueError("window_days 必须为正")
    if sold_units < 0:
        raise ValueError("销量不能为负")

    on_hand = int(row.get("on_hand", 0))
    reserved = int(row.get("reserved", 0))
    inbound = int(row.get("inbound", 0))
    if min(on_hand, reserved, inbound) < 0 or reserved > on_hand:
        raise ValueError(f"库存数据异常: on_hand={on_hand} reserved={reserved} inbound={inbound}")
    available = on_hand - reserved

    daily = (Decimal(sold_units) / Decimal(window_days)).quantize(Decimal("0.01"))
    cover = (Decimal(available) / daily).quantize(Decimal("0.01")) if daily > 0 else None

    reasons: list[str] = []
    if daily == 0:
        if available > params.safety_stock:
            level = LEVEL_SLOW_MOVING
            reasons.append(f"近 {window_days} 天无销量且可售 {available} > 安全库存 "
                           f"{params.safety_stock}，判定滞销（不是库存安全）")
        else:
            level = LEVEL_NO_SALES
            reasons.append(f"近 {window_days} 天无销量，无法估算覆盖天数")
    elif cover < params.lead_time_days:
        level = LEVEL_CRITICAL
        reasons.append(f"可售 {available} 仅够 {cover} 天，短于采购提前期 "
                       f"{params.lead_time_days} 天，存在断货风险")
    elif cover < params.target_cover_days:
        level = LEVEL_WARN
        reasons.append(f"可售可支撑 {cover} 天，低于目标覆盖 {params.target_cover_days} 天")
    else:
        level = LEVEL_OK
        reasons.append(f"可售可支撑 {cover} 天，覆盖充足")

    recommended = 0
    formula = "无需补货"
    if daily > 0 and level in (LEVEL_CRITICAL, LEVEL_WARN):
        target_need = daily * Decimal(params.lead_time_days + params.target_cover_days)
        need = target_need + Decimal(params.safety_stock) - Decimal(available) - Decimal(inbound)
        raw = int(need.to_integral_value(rounding=ROUND_CEILING))
        recommended = max(params.moq, raw, 0)
        formula = (f"ceil(日均 {daily} × (提前期 {params.lead_time_days} + 目标覆盖 "
                   f"{params.target_cover_days}) + 安全库存 {params.safety_stock} - 可售 "
                   f"{available} - 在途 {inbound}) = {raw}，取 MOQ {params.moq} 与需求量的较大值")
    if inbound > 0:
        reasons.append(f"在途 {inbound} 件不计入当前可售，只影响到货后的覆盖")

    return InventoryAnalysis(sku=row.get("sku", ""), asin=row.get("asin", ""),
                             on_hand=on_hand, reserved=reserved, available=available,
                             inbound=inbound, window_days=window_days, sold_units=sold_units,
                             daily_sales=daily, days_of_cover=cover, level=level,
                             recommended_qty=recommended, reasons=tuple(reasons),
                             formula=formula)
