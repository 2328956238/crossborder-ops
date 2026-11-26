"""经营报表服务（Phase 2 基础版；Phase 5 补齐排行/多店铺汇总口径）。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories import ads as ads_repo
from ..core.errors import ValidationError
from ..core.serialization import money
from ..repositories import business as repo
from . import advertising as advertising_service


async def sales_summary(session: AsyncSession, shop_id: str, date_from: date,
                        date_to: date) -> dict:
    """按订单口径统计（created_at 落在区间内）。"""
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
    from sqlalchemy import select

    from ..models import Order

    rows = list((await session.execute(
        select(Order).where(Order.shop_id == shop_id,
                            Order.created_at >= start,
                            Order.created_at <= end))).scalars().all())
    revenue = sum((r.total_amount or Decimal("0") for r in rows), Decimal("0"))
    return {"shop_id": shop_id, "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(), "order_count": len(rows),
            "revenue": revenue,
            "aov": (revenue / len(rows)) if rows else Decimal("0")}


async def ad_summary(session: AsyncSession, shop_id: str, date_from: date, date_to: date) -> dict:
    metrics = await advertising_service.metrics(session, shop_id, date_from=date_from,
                                                date_to=date_to)
    data = dict(metrics)
    for key in ("spend", "sales", "revenue"):
        if key in data:
            data[key] = money(data[key])
    return {"shop_id": shop_id, "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(), **data}


async def inventory_warnings(session: AsyncSession, shop_id: str) -> list[dict]:
    return await repo.low_stock(session, shop_id)


async def multi_shop_overview(session: AsyncSession, shop_ids: list[str], date_from: date,
                              date_to: date) -> list[dict]:
    result = []
    for shop_id in shop_ids:
        sales = await sales_summary(session, shop_id, date_from, date_to)
        ads = await advertising_service.metrics(session, shop_id, date_from=date_from,
                                                date_to=date_to)
        result.append({
            "shop_id": shop_id,
            "orders": sales["order_count"],
            "revenue": str(sales["revenue"]),
            "ad_spend": str(ads["spend"]),
            "roas": ads.get("roas"),
            "acos": ads.get("acos"),
        })
    return result


__all__ = ["sales_summary", "ad_summary", "inventory_warnings", "multi_shop_overview",
           "ads_repo"]


async def top_products(session: AsyncSession, shop_id: str, date_from: date, date_to: date,
                       limit: int = 10) -> list[dict]:
    if limit < 1 or limit > 100:
        raise ValidationError("limit 必须在 1..100")
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
    rows = await repo.top_products(session, shop_id, start=start, end=end, limit=limit)
    return [{"sku": r["sku"], "quantity": r["quantity"], "revenue": money(r["revenue"])}
            for r in rows]


async def ad_trend(session: AsyncSession, shop_id: str, date_from: date, date_to: date) -> list[dict]:
    """按天的广告消耗/点击/转化趋势（ACOS 逐日）。"""
    rows = await ads_repo.list_insights(session, shop_id, date_from=date_from, date_to=date_to)
    daily: dict[str, dict] = {}
    for row in rows:
        key = row.date.isoformat()
        bucket = daily.setdefault(key, {"date": key, "spend": Decimal("0"),
                                        "revenue": Decimal("0"), "clicks": 0,
                                        "impressions": 0, "conversions": Decimal("0")})
        bucket["spend"] += row.spend
        bucket["revenue"] += row.revenue
        bucket["clicks"] += row.clicks
        bucket["impressions"] += row.impressions
        bucket["conversions"] += row.conversions
    series = []
    for key in sorted(daily):
        bucket = daily[key]
        acos = (bucket["spend"] / bucket["revenue"]) if bucket["revenue"] else None
        series.append({"date": key, "spend": money(bucket["spend"]),
                       "revenue": money(bucket["revenue"]),
                       "clicks": bucket["clicks"], "impressions": bucket["impressions"],
                       "acos": None if acos is None else round(float(acos), 6)})
    return series


__all__ += ["top_products", "ad_trend"]
