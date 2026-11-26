"""Meta 数据同步：分页拉取 → 幂等写入 PG（source 明确标记 meta / mock）。"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from .. import metrics
from ..integrations.meta import accounts as meta_accounts
from ..integrations.meta import ads as meta_ads
from ..integrations.meta import adsets as meta_adsets
from ..integrations.meta import campaigns as meta_campaigns
from ..integrations.meta import insights as meta_insights
from ..repositories import ads as repo

logger = logging.getLogger(__name__)


def _source(client) -> str:
    return "mock" if getattr(client, "is_mock", False) else "meta"


def _account_status(value) -> str:
    try:
        return "active" if int(value) == 1 else "inactive"
    except (TypeError, ValueError):
        return str(value or "unknown")


async def sync_accounts(session: AsyncSession, shop_id: str, client) -> int:
    count = 0
    for item in await meta_accounts.list_accounts(client):
        await repo.upsert_account(session, shop_id, {
            "platform": "meta",
            "external_id": item["id"],
            "name": item.get("name", item["id"]),
            "status": _account_status(item.get("account_status")),
            "currency": item.get("currency", "USD"),
            "timezone": item.get("timezone_name", "UTC"),
        })
        count += 1
    metrics.META_SYNC_ROWS.labels("account", _source(client)).inc(count)
    return count


async def sync_campaigns(session: AsyncSession, shop_id: str, client) -> int:
    count = 0
    for account in await repo.list_accounts(session, shop_id):
        for item in await meta_campaigns.list_campaigns(client, account.external_id):
            budget = item.get("daily_budget")
            await repo.upsert_campaign(session, shop_id, account.id, {
                "external_id": item["id"],
                "name": item.get("name", item["id"]),
                "status": item.get("status", "UNKNOWN"),
                "daily_budget": Decimal(str(budget)) if budget else None,
            })
            count += 1
    metrics.META_SYNC_ROWS.labels("campaign", _source(client)).inc(count)
    return count


async def sync_adsets_and_ads(session: AsyncSession, shop_id: str, client) -> tuple[int, int]:
    adsets = ads = 0
    for campaign in await repo.list_campaigns(session, shop_id, limit=500):
        for item in await meta_adsets.list_adsets(client, campaign.external_id):
            budget = item.get("daily_budget")
            adset = await repo.upsert_adset(session, shop_id, campaign.id, {
                "external_id": item["id"],
                "name": item.get("name", item["id"]),
                "status": item.get("status", "UNKNOWN"),
                "daily_budget": Decimal(str(budget)) if budget else None,
            })
            adsets += 1
            for ad_item in await meta_ads.list_ads(client, adset.external_id):
                await repo.upsert_ad(session, shop_id, adset.id, {
                    "external_id": ad_item["id"],
                    "name": ad_item.get("name", ad_item["id"]),
                    "status": ad_item.get("status", "UNKNOWN"),
                })
                ads += 1
    metrics.META_SYNC_ROWS.labels("adset", _source(client)).inc(adsets)
    metrics.META_SYNC_ROWS.labels("ad", _source(client)).inc(ads)
    return adsets, ads


async def sync_insights(session: AsyncSession, shop_id: str, client, *,
                        since: date, until: date) -> int:
    """按账户拉分日指标；唯一键幂等，重复同步只更新不新增。"""
    count = 0
    for account in await repo.list_accounts(session, shop_id):
        rows = await meta_insights.fetch_insights(client, account.external_id,
                                                  since=since, until=until)
        for row in rows:
            row["source"] = _source(client)
            await repo.upsert_insight(session, shop_id, row)
            count += 1
    metrics.META_SYNC_ROWS.labels("insight", _source(client)).inc(count)
    return count


async def sync_all(session: AsyncSession, shop_id: str, client, *,
                   since: date, until: date) -> dict:
    accounts = await sync_accounts(session, shop_id, client)
    campaigns = await sync_campaigns(session, shop_id, client)
    adsets, ads = await sync_adsets_and_ads(session, shop_id, client)
    insights = await sync_insights(session, shop_id, client, since=since, until=until)
    return {"source": _source(client), "accounts": accounts, "campaigns": campaigns,
            "adsets": adsets, "ads": ads, "insights": insights}
