"""AdSet 查询。"""
from __future__ import annotations

from typing import Any

FIELDS = "id,name,status,daily_budget"


async def list_adsets(client, campaign_id: str) -> list[dict[str, Any]]:
    return [item async for item in client.paginate(
        f"{campaign_id}/adsets", {"fields": FIELDS, "limit": 50})]
