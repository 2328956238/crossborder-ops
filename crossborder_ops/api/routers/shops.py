"""店铺路由：读 viewer+；创建店铺仅 admin（并审计）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session
from ...schemas.business import ShopCreate
from ...services import shops as service
from ..deps import get_request_id

router = APIRouter(prefix="/api/v1/shops", tags=["shops"])


@router.get("")
async def list_shops(session: AsyncSession = Depends(get_session),
                     ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    current = await service.get_shop(session, ctx.shop_id)
    return {"ok": True, "data": {"items": [current], "current": ctx.shop_id}}


@router.get("/{shop_id}")
async def get_shop(shop_id: str, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    if shop_id != ctx.shop_id:
        raise HTTPException(status_code=403, detail={"code": "forbidden_shop",
                                                     "message": "只能查看当前店铺"})
    return {"ok": True, "data": await service.get_shop(session, shop_id)}


@router.post("", status_code=201)
async def create_shop(payload: ShopCreate, request: Request,
                      session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(require_role("admin"))):
    data = await service.create_shop(session, ctx, payload)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="shop.create", entity_type="shop", entity_id=data["id"],
        before=None, after=data, request_id=get_request_id(request))
    return {"ok": True, "data": data}
