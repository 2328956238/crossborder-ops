"""广告域服务：账户/结构查询、Insights 幂等写入与指标计算。"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import ConflictError
from ..core.permissions import ensure_role
from ..core.security import ShopContext
from ..domain import advertising as ad_domain
from ..repositories import ads as repo


async def list_accounts(session: AsyncSession, shop_id: str) -> list[dict]:
    return [{"id": a.id, "external_id": a.external_id, "name": a.name, "platform": a.platform,
             "status": a.status, "currency": a.currency} for a in
            await repo.list_accounts(session, shop_id)]


async def create_account(session: AsyncSession, ctx: ShopContext, payload) -> dict:
    ensure_role(ctx, "operator", "admin")
    shop_id = ctx.shop_id
    account = await repo.create_account(
        session, shop_id, id=str(uuid.uuid4()), external_id=payload.external_id,
        name=payload.name, platform=payload.platform, currency=payload.currency)
    return {"id": account.id, "external_id": account.external_id, "name": account.name,
            "platform": account.platform, "status": account.status,
            "currency": account.currency}


async def list_campaigns(session: AsyncSession, shop_id: str) -> list[dict]:
    return [{"id": c.id, "external_id": c.external_id, "name": c.name, "status": c.status,
             "daily_budget": c.daily_budget} for c in await repo.list_campaigns(session, shop_id)]


async def list_adsets(session: AsyncSession, shop_id: str) -> list[dict]:
    return [{"id": s.id, "external_id": s.external_id, "name": s.name, "status": s.status}
            for s in await repo.list_adsets(session, shop_id)]


async def list_ads(session: AsyncSession, shop_id: str) -> list[dict]:
    return [{"id": a.id, "external_id": a.external_id, "name": a.name, "status": a.status}
            for a in await repo.list_ads(session, shop_id)]


async def upsert_insight(session: AsyncSession, ctx: ShopContext, payload) -> dict:
    ensure_role(ctx, "operator", "admin")
    shop_id = ctx.shop_id
    row = await repo.upsert_insight(session, shop_id, payload.model_dump())
    return {"level": row.level, "entity_external_id": row.entity_external_id,
            "date": row.date.isoformat(), "impressions": row.impressions,
            "clicks": row.clicks, "spend": row.spend, "conversions": row.conversions,
            "revenue": row.revenue}


async def metrics(session: AsyncSession, shop_id: str, *, date_from: date, date_to: date) -> dict:
    rows = await repo.list_insights(session, shop_id, date_from=date_from, date_to=date_to)
    totals = {
        "impressions": sum(r.impressions for r in rows),
        "clicks": sum(r.clicks for r in rows),
        "spend": sum((r.spend for r in rows), Decimal("0")),
        "conversions": sum((r.conversions for r in rows), Decimal("0")),
        "revenue": sum((r.revenue for r in rows), Decimal("0")),
    }
    computed = ad_domain.compute_metrics(
        spend=float(totals["spend"]), clicks=totals["clicks"],
        orders=int(totals["conversions"]), impressions=totals["impressions"],
        sales=float(totals["revenue"]))
    result = computed.to_dict()
    result.update({k: totals[k] for k in ("impressions", "clicks")})
    return result


__all__ = ["list_accounts", "create_account", "list_campaigns", "list_adsets", "list_ads",
           "upsert_insight", "metrics", "ConflictError"]
