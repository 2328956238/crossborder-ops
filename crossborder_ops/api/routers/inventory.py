"""库存路由：读 viewer+；upsert/adjust 为低风险直接写（operator+），全部审计。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session, get_sessionmaker
from ...schemas.business import InventoryAdjust, InventoryUpsert
from ...services import inventory as service
from ..deps import get_request_id

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("")
async def list_inventory(low_only: bool = Query(default=False),
                         limit: int = Query(default=100, ge=1, le=500),
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    items = await service.list_inventory(session, ctx.shop_id, low_only=low_only, limit=limit)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/low-stock")
async def low_stock(session: AsyncSession = Depends(get_session),
                    ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    return {"ok": True, "data": {"items": await service.low_stock(session, ctx.shop_id)}}


@router.put("/{sku}")
async def upsert_inventory(sku: str, payload: InventoryUpsert, request: Request,
                           session: AsyncSession = Depends(get_session),
                           ctx: ShopContext = Depends(require_role("operator", "admin"))):
    payload = payload.model_copy(update={"sku": sku})
    before = await service.get(session, ctx.shop_id, sku)
    data = await service.upsert(session, ctx, payload)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="inventory.upsert", entity_type="inventory", entity_id=sku,
        before=before, after=data, request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.post("/{sku}/adjust")
async def adjust_inventory(sku: str, payload: InventoryAdjust, request: Request,
                           session: AsyncSession = Depends(get_session),
                           ctx: ShopContext = Depends(require_role("operator", "admin"))):
    before = await service.get(session, ctx.shop_id, sku)
    try:
        data = await service.adjust(session, ctx, sku, payload)
    except Exception as exc:  # noqa: BLE001
        await audit_core.record_failure_for_request(
            get_sessionmaker(), ctx=ctx, request_id=get_request_id(request),
            action="inventory.adjust", entity_type="inventory", entity_id=sku,
            exc=exc, before=before)
        raise
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="inventory.adjust", entity_type="inventory", entity_id=sku,
        before=before, after=data, request_id=get_request_id(request))
    return {"ok": True, "data": data}
