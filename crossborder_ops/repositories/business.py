"""基础业务仓储：shops / products / orders / inventory。所有函数强制 shop_id。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Inventory, Order, Product, Shop


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------- shops ----------------
async def get_shop(session: AsyncSession, shop_id: str) -> Shop | None:
    return await session.get(Shop, shop_id)


async def list_shops(session: AsyncSession) -> list[Shop]:
    return list((await session.execute(select(Shop).order_by(Shop.id))).scalars().all())


async def create_shop(session: AsyncSession, **kwargs) -> Shop:
    shop = Shop(**kwargs)
    session.add(shop)
    await session.flush()
    return shop


# ---------------- products ----------------
async def list_products(session: AsyncSession, shop_id: str, *, status: str | None = None,
                        limit: int = 50, offset: int = 0) -> list[Product]:
    q = select(Product).where(Product.shop_id == shop_id)
    if status:
        q = q.where(Product.status == status)
    q = q.order_by(Product.sku).limit(limit).offset(offset)
    return list((await session.execute(q)).scalars().all())


async def get_product(session: AsyncSession, shop_id: str, sku: str) -> Product | None:
    return (await session.execute(
        select(Product).where(Product.shop_id == shop_id, Product.sku == sku))).scalar_one_or_none()


async def create_product(session: AsyncSession, shop_id: str, **kwargs) -> Product:
    product = Product(shop_id=shop_id, updated_at=now_iso(), **kwargs)
    session.add(product)
    await session.flush()
    return product


# ---------------- orders ----------------
async def list_orders(session: AsyncSession, shop_id: str, *, status: str | None = None,
                      limit: int = 50, offset: int = 0) -> list[Order]:
    q = select(Order).where(Order.shop_id == shop_id)
    if status:
        q = q.where(Order.status == status)
    q = q.order_by(Order.id.desc()).limit(limit).offset(offset)
    return list((await session.execute(q)).scalars().all())


async def get_order(session: AsyncSession, shop_id: str, order_id: str) -> Order | None:
    return (await session.execute(
        select(Order).where(Order.shop_id == shop_id, Order.order_id == order_id))).scalar_one_or_none()


async def order_stats(session: AsyncSession, shop_id: str, days: int = 7) -> dict:
    """按最近 N 天统计（使用 created_at；无 created_at 的历史数据按全部计）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = select(Order).where(Order.shop_id == shop_id, Order.created_at >= since)
    rows = list((await session.execute(base)).scalars().all())
    revenue = sum((o.total_amount or Decimal("0") for o in rows), Decimal("0"))
    by_status: dict[str, int] = {}
    for order in rows:
        by_status[order.status] = by_status.get(order.status, 0) + 1
    return {"days": days, "order_count": len(rows), "revenue": revenue, "by_status": by_status}


# ---------------- inventory ----------------
async def list_inventory(session: AsyncSession, shop_id: str, *, low_only: bool = False,
                         limit: int = 100) -> list[Inventory]:
    q = select(Inventory).where(Inventory.shop_id == shop_id).order_by(Inventory.sku).limit(limit)
    if low_only:
        q = q.where(Inventory.on_hand - Inventory.reserved <= Inventory.safety_stock)
    return list((await session.execute(q)).scalars().all())


async def get_inventory(session: AsyncSession, shop_id: str, sku: str) -> Inventory | None:
    return (await session.execute(
        select(Inventory).where(Inventory.shop_id == shop_id,
                                Inventory.sku == sku))).scalar_one_or_none()


async def low_stock(session: AsyncSession, shop_id: str) -> list[dict]:
    rows = await list_inventory(session, shop_id, low_only=True, limit=500)
    return [{"sku": r.sku, "available": r.on_hand - r.reserved,
             "safety_stock": r.safety_stock,
             "shortage": max(0, r.safety_stock - (r.on_hand - r.reserved))} for r in rows]


async def inventory_count(session: AsyncSession, shop_id: str) -> int:
    return (await session.execute(
        select(func.count()).select_from(Inventory).where(Inventory.shop_id == shop_id))).scalar_one()


# ---------------- 商品销售排行（阶段 5） ----------------
async def add_order_item(session: AsyncSession, shop_id: str, *, order_id: str, sku: str,
                         quantity: int, unit_amount: Decimal,
                         currency: str = "USD") -> "OrderItem":
    from ..models import OrderItem

    item = OrderItem(shop_id=shop_id, order_id=order_id, sku=sku, quantity=quantity,
                     unit_amount=unit_amount, currency=currency)
    session.add(item)
    await session.flush()
    return item


async def top_products(session: AsyncSession, shop_id: str, *, start, end,
                       limit: int = 10) -> list[dict]:
    from ..models import Order, OrderItem

    q = (select(OrderItem.sku,
                func.sum(OrderItem.quantity).label("quantity"),
                func.sum(OrderItem.quantity * OrderItem.unit_amount).label("revenue"))
         .join(Order, (Order.shop_id == OrderItem.shop_id) & (Order.order_id == OrderItem.order_id))
         .where(OrderItem.shop_id == shop_id, Order.created_at >= start,
                Order.created_at <= end)
         .group_by(OrderItem.sku)
         .order_by(func.sum(OrderItem.quantity * OrderItem.unit_amount).desc())
         .limit(limit))
    rows = (await session.execute(q)).all()
    return [{"sku": r[0], "quantity": int(r[1] or 0), "revenue": Decimal(str(r[2] or 0))}
            for r in rows]
