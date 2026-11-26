"""Insights 分时段同步：按天拉取，分页，原始行 -> 结构化指标。"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

FIELDS = "date_start,date_stop,impressions,clicks,spend,actions,action_values"


def _sum_action(values: list[dict] | None, action_type: str) -> Decimal:
    total = Decimal("0")
    for item in values or []:
        if item.get("action_type") == action_type:
            try:
                total += Decimal(str(item.get("value", "0")))
            except Exception:  # noqa: BLE001 - 平台偶发脏数据不影响整批
                continue
    return total


def normalize_row(row: dict[str, Any], *, level: str, entity_id: str) -> dict:
    day = row.get("date_start") or row.get("date_stop")
    return {
        "level": level,
        "entity_external_id": entity_id,
        "date": date.fromisoformat(str(day)),
        "impressions": int(row.get("impressions") or 0),
        "clicks": int(row.get("clicks") or 0),
        "spend": Decimal(str(row.get("spend") or "0")),
        "conversions": _sum_action(row.get("actions"), "purchase"),
        "revenue": _sum_action(row.get("action_values"), "purchase"),
    }


async def fetch_insights(client, account_id: str, *, since: date, until: date,
                         level: str = "account") -> list[dict]:
    params = {
        "level": level,
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "time_increment": 1,
        "fields": FIELDS,
        "limit": 100,
    }
    rows = [item async for item in client.paginate(f"{account_id}/insights", params)]
    return [normalize_row(row, level=level, entity_id=account_id) for row in rows]
