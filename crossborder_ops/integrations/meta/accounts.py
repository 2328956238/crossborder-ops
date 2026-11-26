"""广告账户查询。"""
from __future__ import annotations

from typing import Any

FIELDS = "id,name,account_status,currency,timezone_name"


async def list_accounts(client) -> list[dict[str, Any]]:
    return [item async for item in client.paginate(
        "me/adaccounts", {"fields": FIELDS, "limit": 50})]
