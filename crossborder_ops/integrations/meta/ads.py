"""Ad 查询。"""
from __future__ import annotations

from typing import Any

FIELDS = "id,name,status"


async def list_ads(client, adset_id: str) -> list[dict[str, Any]]:
    return [item async for item in client.paginate(
        f"{adset_id}/ads", {"fields": FIELDS, "limit": 50})]
