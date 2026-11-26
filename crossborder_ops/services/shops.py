"""店铺服务：店铺是租户边界，只允许 admin 创建。"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import AppError, ConflictError, NotFoundError
from ..repositories import business as repo


async def list_shops(session: AsyncSession) -> list[dict]:
    return [{"id": s.id, "name": s.name, "marketplace": s.marketplace,
             "currency": s.currency, "timezone": s.timezone, "status": s.status} for s in
            await repo.list_shops(session)]


async def get_shop(session: AsyncSession, shop_id: str) -> dict:
    shop = await repo.get_shop(session, shop_id)
    if shop is None:
        raise NotFoundError(f"店铺不存在: {shop_id}")
    return {"id": shop.id, "name": shop.name, "marketplace": shop.marketplace,
            "currency": shop.currency, "timezone": shop.timezone, "status": shop.status}


async def ensure_shop(session: AsyncSession, shop_id: str) -> None:
    """webhook / 内部任务用：店铺不存在时自动创建（不对外暴露）。"""
    if await repo.get_shop(session, shop_id) is None:
        await repo.create_shop(session, id=shop_id, name=shop_id)


async def create_shop(session: AsyncSession, payload) -> dict:
    if await repo.get_shop(session, payload.id) is not None:
        raise ConflictError(f"店铺已存在: {payload.id}")
    shop = await repo.create_shop(session, id=payload.id, name=payload.name,
                                  marketplace=payload.marketplace,
                                  currency=payload.currency, timezone=payload.timezone)
    return {"id": shop.id, "name": shop.name, "marketplace": shop.marketplace,
            "currency": shop.currency, "timezone": shop.timezone, "status": shop.status}


__all__ = ["list_shops", "get_shop", "ensure_shop", "create_shop", "AppError"]
