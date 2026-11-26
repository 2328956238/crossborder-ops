"""库存服务：upsert（幂等）与增量调整，可售 = on_hand − reserved（不为负）。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import NotFoundError, ValidationError
from ..repositories import business as repo


def _to_dict(row) -> dict:
    return {"id": row.id, "sku": row.sku, "warehouse": row.warehouse,
            "on_hand": row.on_hand, "reserved": row.reserved, "inbound": row.inbound,
            "available": row.on_hand - row.reserved, "safety_stock": row.safety_stock,
            "lead_time_days": row.lead_time_days}


async def list_inventory(session: AsyncSession, shop_id: str, *, low_only: bool = False,
                         limit: int = 100) -> list[dict]:
    if limit < 1 or limit > 500:
        raise ValidationError("limit 必须在 1..500")
    return [_to_dict(r) for r in await repo.list_inventory(session, shop_id,
                                                           low_only=low_only, limit=limit)]


async def upsert(session: AsyncSession, shop_id: str, payload) -> dict:
    if payload.reserved > payload.on_hand:
        raise ValidationError("reserved 不能大于 on_hand")
    row = await repo.get_inventory(session, shop_id, payload.sku)
    values = dict(warehouse=payload.warehouse, on_hand=payload.on_hand,
                  reserved=payload.reserved, inbound=payload.inbound,
                  safety_stock=payload.safety_stock, lead_time_days=payload.lead_time_days,
                  quantity=payload.on_hand - payload.reserved, updated_at=repo.now_iso())
    if row is None:
        from ..models import Inventory
        row = Inventory(shop_id=shop_id, sku=payload.sku, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.flush()
    return _to_dict(row)


async def adjust(session: AsyncSession, shop_id: str, sku: str, payload) -> dict:
    row = await repo.get_inventory(session, shop_id, sku)
    if row is None:
        raise NotFoundError(f"库存记录不存在: {sku}")
    on_hand = row.on_hand + payload.on_hand_delta
    reserved = row.reserved + payload.reserved_delta
    inbound = row.inbound + payload.inbound_delta
    if on_hand < 0 or reserved < 0 or inbound < 0:
        raise ValidationError("调整后数量不能为负")
    if reserved > on_hand:
        raise ValidationError("reserved 不能大于 on_hand")
    row.on_hand, row.reserved, row.inbound = on_hand, reserved, inbound
    row.quantity = on_hand - reserved
    row.updated_at = repo.now_iso()
    await session.flush()
    return _to_dict(row)


async def low_stock(session: AsyncSession, shop_id: str) -> list[dict]:
    return await repo.low_stock(session, shop_id)
