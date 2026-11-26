"""Meta Mock 适配器：无真实凭证时使用，**绝不伪造真实调用成功**。

所有返回都带 mock 标记；接口形状与真实客户端一致，方便上层代码零改动切换。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any


class MockMetaClient:
    is_mock = True
    source = "mock"

    def __init__(self, page_size: int = 2):
        self.page_size = page_size
        self.calls: list[tuple[str, dict]] = []

    def describe(self) -> dict:
        return {
            "mock": True,
            "source": "mock",
            "note": "未配置真实 Meta 凭证，当前返回合成数据，不代表真实投放结果",
        }

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        self.calls.append((path, dict(params or {})))
        items = self._items_for(path)
        return {"data": items, "mock": True, "source": "mock",
                "paging": {"cursors": {"after": None}}}

    async def paginate(self, path: str, params: dict[str, Any] | None = None,
                       *, max_pages: int = 20) -> AsyncIterator[dict]:
        self.calls.append((path, dict(params or {})))
        items = self._items_for(path)
        for start in range(0, len(items), self.page_size):
            for item in items[start:start + self.page_size]:
                yield item

    def _items_for(self, path: str) -> list[dict]:
        if "adaccounts" in path or path.endswith("/accounts"):
            return [
                {"id": "act_mock_1", "name": "Mock 广告账户 A", "account_status": 1,
                 "currency": "USD", "timezone_name": "America/Los_Angeles"},
                {"id": "act_mock_2", "name": "Mock 广告账户 B", "account_status": 1,
                 "currency": "USD", "timezone_name": "UTC"},
            ]
        if path.endswith("/campaigns"):
            return [{"id": "camp_mock_1", "name": "Mock Campaign 1", "status": "ACTIVE",
                     "objective": "OUTCOME_SALES", "daily_budget": "1000"},
                    {"id": "camp_mock_2", "name": "Mock Campaign 2", "status": "PAUSED",
                     "objective": "OUTCOME_TRAFFIC", "daily_budget": "500"}]
        if path.endswith("/adsets"):
            return [{"id": "adset_mock_1", "name": "Mock AdSet 1", "status": "ACTIVE",
                     "daily_budget": "300"}]
        if path.endswith("/ads"):
            return [
                {"id": "ad_mock_1", "name": "Mock Ad 1", "status": "ACTIVE",
                 "effective_status": "ACTIVE", "issues_info": []},
                {"id": "ad_mock_2", "name": "Mock Ad 2", "status": "PAUSED",
                 "effective_status": "DISAPPROVED",
                 "issues_info": [{"error_code": "1885183", "error_summary": "广告被拒审"}]},
                {"id": "ad_mock_3", "name": "Mock Ad 3", "status": "PAUSED",
                 "effective_status": "WITH_ISSUES", "issues_info": []},
            ]
        if path.endswith("/insights"):
            base = date(2026, 3, 1)
            return [{"date_start": (base + timedelta(days=i)).isoformat(),
                     "date_stop": (base + timedelta(days=i)).isoformat(),
                     "impressions": "1000", "clicks": str(10 + i), "spend": "5.00",
                     "actions": [{"action_type": "purchase", "value": "2"}],
                     "action_values": [{"action_type": "purchase", "value": "20.00"}]}
                    for i in range(3)]
        return []
