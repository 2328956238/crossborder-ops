"""API 序列化辅助：金额统一输出 4 位小数字符串，避免 JSON 浮点误差。"""
from __future__ import annotations

from decimal import Decimal

MONEY_QUANT = Decimal("0.0001")


def money(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(MONEY_QUANT))
