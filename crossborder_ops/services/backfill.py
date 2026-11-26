from datetime import datetime, timedelta

from sqlalchemy import text

from .events import UPSERT_ORDER

EPOCH = "1970-01-01T00:00:00+00:00"
OVERLAP = timedelta(minutes=5)   # 回退窗口，防止边界漏数据；重复由幂等写入吸收


def _minus_overlap(ts: str) -> str:
    if ts == EPOCH:
        return ts
    return (datetime.fromisoformat(ts) - OVERLAP).isoformat()


async def backfill_orders(session, client, shop_id: str) -> int:
    cur = (await session.execute(
        text("SELECT value FROM sync_cursor WHERE shop_id=:s AND name='orders'"),
        {"s": shop_id})).scalar_one_or_none()
    await session.rollback()  # 结束读取产生的隐式事务
    since = _minus_overlap(cur or EPOCH)

    data = await client.get("/orders", shop_id, "orders", updated_after=since)
    orders = data["orders"]

    async with session.begin():
        for o in orders:
            await session.execute(UPSERT_ORDER, {
                "shop_id": shop_id, "order_id": o["order_id"],
                "status": o["status"], "ts": o["last_update_time"],
            })
        if orders:
            # 水位线只在这一批全部写入成功后，随同一个事务推进
            newest = max(o["last_update_time"] for o in orders)
            await session.execute(text("""
                INSERT INTO sync_cursor (shop_id, name, value) VALUES (:s, 'orders', :v)
                ON CONFLICT (shop_id, name) DO UPDATE SET value = excluded.value
                WHERE sync_cursor.value < excluded.value
            """), {"s": shop_id, "v": newest})
    return len(orders)
