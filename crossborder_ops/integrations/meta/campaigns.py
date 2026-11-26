"""Campaign 查询。"""
from __future__ import annotations

from typing import Any

FIELDS = "id,name,status,objective,daily_budget"


async def list_campaigns(client, account_id: str) -> list[dict[str, Any]]:
    return [item async for item in client.paginate(
        f"{account_id}/campaigns", {"fields": FIELDS, "limit": 50})]
