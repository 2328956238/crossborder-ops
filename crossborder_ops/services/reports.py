"""经营报表服务（Phase 2 基础版；Phase 5 补齐排行/多店铺汇总口径）。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories import ads as ads_repo
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
