"""订单服务：只读查询 + 统计（写入由 webhook 同步负责）。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import NotFoundError, ValidationError
from ..core.serialization import money
from ..repositories import business as repo


def _to_dict(order) -> dict:
    return {"id": order.id, "order_id": order.order_id, "status": order.status,
            "last_update_time": order.last_update_time, "version": order.version,
            "total_amount": money(order.total_amount), "currency": order.currency,
            "channel": order.channel}


async def list_orders(session: AsyncSession, shop_id: str, *, status: str | None = None,
                      limit: int = 50, offset: int = 0) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ValidationError("limit 必须在 1..200")
    rows = await repo.list_orders(session, shop_id, status=status, limit=limit, offset=offset)
    return [_to_dict(o) for o in rows]


async def get_order(session: AsyncSession, shop_id: str, order_id: str) -> dict:
    order = await repo.get_order(session, shop_id, order_id)
    if order is None:
        raise NotFoundError(f"订单不存在: {order_id}")
    return _to_dict(order)


async def stats(session: AsyncSession, shop_id: str, days: int = 7) -> dict:
    if days < 1 or days > 365:
        raise ValidationError("days 必须在 1..365")
    return await repo.order_stats(session, shop_id, days=days)
