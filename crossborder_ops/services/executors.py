"""Action Registry：每类业务操作对应一个执行器。

约束：
- 只有登记在 `EXECUTORS` 里的 action_type 才能被执行；
- 执行器只操作 Local/Mock Adapter 的覆盖层，**不触碰真实平台**；
- 执行前必须重新读取当前值并与 before_snapshot 比对（防覆盖别人修改）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

try:  # httpx 是项目已有依赖，缺失也不影响本地执行
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


class ActionError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def is_unknown_error(exc: BaseException) -> bool:
    """超时/网络中断 = 结果未知，不能当失败，也不能自动重试或回滚。"""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    if httpx is not None and isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return False


@runtime_checkable
class ActionExecutor(Protocol):
    action_type: str
    agent_type: str
    risk_action: str

    def read_current(self, data: Any, shop_id: str, target_id: str) -> dict: ...

    def validate(self, before: dict, after: dict, current: dict) -> list[str]: ...

    def apply(self, data: Any, shop_id: str, target_id: str, after: dict) -> dict: ...


@dataclass
class ListingExecutor:
    """商品 Listing 修改（标题/描述/Bullet/图片/状态）。"""

    action_type: str = "product.update_listing"
    agent_type: str = "product"
    risk_action: str = "update_listing"
    editable: tuple[str, ...] = ("title", "description", "bullets", "images", "listing_status")

    def read_current(self, data, shop_id: str, target_id: str) -> dict:
        return data.listing_snapshot(shop_id, target_id)

    def validate(self, before: dict, after: dict, current: dict) -> list[str]:
        problems: list[str] = []
        unknown = set(after) - set(self.editable)
        if unknown:
            problems.append(f"unsupported_fields:{','.join(sorted(unknown))}")
        if not after:
            problems.append("empty_after_snapshot")
        for key, value in before.items():
            if key in current and current[key] != value:
                problems.append(f"stale_before_value:{key}")
        if "images" in after:
            from ..domain.catalog import IMAGE_URL_RE
            for url in after.get("images") or []:
                if not isinstance(url, str) or not IMAGE_URL_RE.match(url):
                    problems.append("invalid_image_url")
                    break
        if "title" in after and not str(after.get("title") or "").strip():
            problems.append("empty_title")
        return problems

    def apply(self, data, shop_id: str, target_id: str, after: dict) -> dict:
        return data.apply_listing(shop_id, target_id, after)


@dataclass
class PriceExecutor:
    action_type: str = "pricing.update_price"
    agent_type: str = "pricing"
    risk_action: str = "update_price"

    def read_current(self, data, shop_id: str, target_id: str) -> dict:
        row = data.pricing_row(shop_id, target_id)
        return {"price": row["price"]}

    def validate(self, before: dict, after: dict, current: dict) -> list[str]:
        problems: list[str] = []
        try:
            price = float((after or {}).get("price"))
        except (TypeError, ValueError):
            return ["invalid_price"]
        if price <= 0:
            problems.append("price_must_be_positive")
        min_p, max_p = current.get("min_price"), current.get("max_price")
        if min_p is not None and price < float(min_p):
            problems.append("below_min_price")
        if max_p is not None and price > float(max_p):
            problems.append("above_max_price")
        if current.get("price") is not None and abs(float(current["price"]) - float(before.get("price", -1))) > 1e-9:
            problems.append("stale_before_value:price")
        return problems

    def apply(self, data, shop_id: str, target_id: str, after: dict) -> dict:
        return data.apply_price(shop_id, target_id, float(after["price"]))


EXECUTORS: dict[str, ActionExecutor] = {
    e.action_type: e for e in (ListingExecutor(), PriceExecutor())
}
