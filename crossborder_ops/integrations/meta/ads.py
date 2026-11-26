"""Ad 查询。"""
from __future__ import annotations

from typing import Any

FIELDS = "id,name,status"


async def list_ads(client, adset_id: str) -> list[dict[str, Any]]:
    return [item async for item in client.paginate(
        f"{adset_id}/ads", {"fields": FIELDS, "limit": 50})]


REVIEW_FIELDS = "id,name,status,effective_status,issues_info"


async def list_ads_with_review(client, adset_id: str) -> list[dict]:
    """广告 + 审核状态；issues_info 可能缺失（平台有时不返回原因）。"""
    return [item async for item in client.paginate(
        f"{adset_id}/ads", {"fields": REVIEW_FIELDS, "limit": 50})]
