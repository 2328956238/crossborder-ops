"""商品服务。"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..core.serialization import money
from ..repositories import business as repo


async def list_products(session: AsyncSession, shop_id: str, *, status: str | None = None,
                        limit: int = 50, offset: int = 0) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ValidationError("limit 必须在 1..200")
    rows = await repo.list_products(session, shop_id, status=status, limit=limit, offset=offset)
    return [{"id": p.id, "shop_id": shop_id, "sku": p.sku, "asin": p.asin, "title": p.title,
             "status": p.status, "price": money(p.price), "currency": p.currency} for p in rows]


async def get_product(session: AsyncSession, shop_id: str, sku: str) -> dict:
    product = await repo.get_product(session, shop_id, sku)
    if product is None:
        raise NotFoundError(f"商品不存在: {sku}")
    return {"id": product.id, "shop_id": product.shop_id, "sku": product.sku, "asin": product.asin, "title": product.title,
            "status": product.status, "price": money(product.price), "currency": product.currency}


async def create_product(session: AsyncSession, shop_id: str, payload) -> dict:
    if await repo.get_product(session, shop_id, payload.sku) is not None:
        raise ConflictError(f"商品已存在: {payload.sku}")
    product = await repo.create_product(
        session, shop_id, id=str(uuid.uuid4()), sku=payload.sku, title=payload.title,
        asin=payload.asin, price=payload.price, currency=payload.currency)
    return {"id": product.id, "shop_id": product.shop_id, "sku": product.sku, "asin": product.asin, "title": product.title,
            "status": product.status, "price": money(product.price), "currency": product.currency}


async def update_product(session: AsyncSession, shop_id: str, sku: str, payload) -> dict:
    product = await repo.get_product(session, shop_id, sku)
    if product is None:
        raise NotFoundError(f"商品不存在: {sku}")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(product, key, value)
    if data:
        product.updated_at = repo.now_iso()
    return {"id": product.id, "shop_id": product.shop_id, "sku": product.sku, "asin": product.asin, "title": product.title,
            "status": product.status, "price": money(product.price), "currency": product.currency}
