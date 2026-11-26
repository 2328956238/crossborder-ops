"""Adapter 协议与真实平台的占位实现。

原则：
1. Protocol 只描述能力，不描述实现；
2. 真实 Amazon Ads API / SP-API 本阶段只有接口骨架，**任何方法都抛 NotImplementedError**；
3. 没有凭证时构造真实 Adapter 直接抛 AdapterNotConfigured，而不是"看起来能用"的空壳；
4. 业务代码只能依赖 Protocol，不能 import 具体的 mock 实现。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class AdPlatformMode(str, Enum):
    """平台模式。业务侧据此决定是否允许写操作、是否需要人类确认。"""

    LOCAL = "local"          # 内存实现，测试/演示
    MOCK = "mock"            # 本地模拟服务（mock_amazon）
    SANDBOX = "sandbox"      # 平台官方测试环境
    PRODUCTION = "production"  # 真实环境


class AdapterError(Exception):
    """Adapter 层统一异常，带稳定错误码，方便 API 层映射。"""

    code = "adapter_error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class AdapterNotConfigured(AdapterError):
    """需要凭证/环境但没配置。绝不静默降级成 mock。"""

    code = "adapter_not_configured"


class AdapterNotImplemented(AdapterError):
    """接口已定义、实现未接入。用于真实 SP-API / Ads API。"""

    code = "adapter_not_implemented"


# ---------------------------------------------------------------------------
# 广告平台（当前唯一有实现的写操作目标）
# ---------------------------------------------------------------------------
@runtime_checkable
class AdsAdapter(Protocol):
    """广告平台读写接口。

    注意：**写方法只允许被 agent/approval.py 的 execute() 调用**。
    Adapter 本身不判断审批，审批永远在 approval 层。
    """

    mode: AdPlatformMode

    async def get_bid(self, shop_id: str, keyword_id: str) -> float: ...

    async def set_bid(self, shop_id: str, keyword_id: str, value: float,
                      idempotency_key: str) -> None: ...


# ---------------------------------------------------------------------------
# 卖家平台（订单 / 库存，当前只读）
# ---------------------------------------------------------------------------
@runtime_checkable
class SpApiAdapter(Protocol):
    """卖家平台只读接口。本阶段不定义任何写方法——没有授权就不可能有写。"""

    mode: AdPlatformMode

    async def list_orders(self, shop_id: str, updated_after: str | None = None) -> list[dict[str, Any]]: ...

    async def get_inventory(self, shop_id: str, sku: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# 真实平台占位（未接入）
# ---------------------------------------------------------------------------
class AmazonAdsApiAdapter:
    """真实 Amazon Ads API —— 未接入。

    构造需要 refresh_token / client_id / client_secret / profile_id；
    任何一个缺失都抛 AdapterNotConfigured，避免"看起来接上了"。
    """

    mode = AdPlatformMode.PRODUCTION

    REQUIRED = ("client_id", "client_secret", "refresh_token", "profile_id")

    def __init__(self, **credentials: Any):
        missing = [k for k in self.REQUIRED if not credentials.get(k)]
        if missing:
            raise AdapterNotConfigured(
                f"Amazon Ads API 未配置，缺少: {', '.join(missing)}", code="ads_api_not_configured")
        raise AdapterNotImplemented(
            "Amazon Ads API 适配器尚未实现（本阶段只定义接口）", code="ads_api_not_implemented")

    async def get_bid(self, shop_id: str, keyword_id: str) -> float:
        raise NotImplementedError("Amazon Ads API 未接入")

    async def set_bid(self, shop_id: str, keyword_id: str, value: float,
                      idempotency_key: str) -> None:
        raise NotImplementedError("Amazon Ads API 未接入")


class AmazonSpApiAdapter:
    """真实 Amazon SP-API —— 未接入。"""

    mode = AdPlatformMode.PRODUCTION

    REQUIRED = ("lwa_client_id", "lwa_client_secret", "refresh_token")

    def __init__(self, **credentials: Any):
        missing = [k for k in self.REQUIRED if not credentials.get(k)]
        if missing:
            raise AdapterNotConfigured(
                f"SP-API 未配置，缺少: {', '.join(missing)}", code="sp_api_not_configured")
        raise AdapterNotImplemented(
            "SP-API 适配器尚未实现（本阶段只定义接口）", code="sp_api_not_implemented")

    async def list_orders(self, shop_id: str, updated_after: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("SP-API 未接入")

    async def get_inventory(self, shop_id: str, sku: str) -> dict[str, Any]:
        raise NotImplementedError("SP-API 未接入")


# ---------------------------------------------------------------------------
# 安全辅助
# ---------------------------------------------------------------------------
def describe_mode(mode: AdPlatformMode) -> str:
    """给 API 响应/日志用的诚实描述，避免把 mock 写成真实。"""
    return {
        AdPlatformMode.LOCAL: "local（内存实现，仅测试/演示，不是真实 Amazon）",
        AdPlatformMode.MOCK: "mock（本地模拟服务，不是真实 Amazon API）",
        AdPlatformMode.SANDBOX: "sandbox（平台测试环境）",
        AdPlatformMode.PRODUCTION: "production（真实授权环境）",
    }[mode]


def require_non_production(adapter: AdPlatformMode | AdsAdapter) -> None:
    """当前阶段禁止写真实环境；调用方在写操作前显式调用，失败就 fail-closed。"""
    mode = adapter if isinstance(adapter, AdPlatformMode) else adapter.mode
    if mode is AdPlatformMode.PRODUCTION:
        raise AdapterError("当前阶段禁止对生产环境执行写操作", code="production_write_blocked")
