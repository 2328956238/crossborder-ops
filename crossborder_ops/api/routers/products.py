"""商品路由：读接口 viewer+；创建 operator+（审计）；Listing/售价修改走审批（不直写）。

兼容说明：`PATCH /products/{sku}` 语义从"直接改"变更为"提交审批"（202），
这是本轮整改的预期变更，旧调用方需改为轮询 operation 状态。
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.errors import ValidationError
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session, get_sessionmaker
from ...schemas.business import ProductCreate, ProductUpdate
from ...schemas.operations import OperationCreate
from ...services import catalog as service
from ...services import operation_submission
from ..deps import get_auth_context, get_request_id

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("")
async def list_products(status: str | None = Query(default=None, max_length=16),
                        limit: int = Query(default=50, ge=1, le=200),
                        offset: int = Query(default=0, ge=0),
                        session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    items = await service.list_products(session, ctx.shop_id, status=status,
                                        limit=limit, offset=offset)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/{sku}")
async def get_product(sku: str, session: AsyncSession = Depends(get_session),
                      ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    return {"ok": True, "data": await service.get_product(session, ctx.shop_id, sku)}


@router.post("", status_code=201)
async def create_product(payload: ProductCreate, request: Request,
                         session: AsyncSession = Depends(get_session),
                         ctx: ShopContext = Depends(require_role("operator", "admin"))):
    try:
        data = await service.create_product(session, ctx, payload)
    except Exception as exc:  # noqa: BLE001 - 失败留痕后继续抛
        await audit_core.record_failure_for_request(
            get_sessionmaker(), ctx=ctx, request_id=get_request_id(request),
            action="product.create", entity_type="product", entity_id=payload.sku,
            exc=exc)
        raise
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="product.create", entity_type="product", entity_id=data["sku"],
        before=None,
        after={"sku": data["sku"], "title": data["title"], "price": data["price"],
               "status": data["status"]},
        request_id=get_request_id(request))
    return {"ok": True, "data": data}


@router.patch("/{sku}", status_code=202)
async def update_product(sku: str, payload: ProductUpdate, request: Request,
                         ctx: ShopContext = Depends(require_role("operator", "admin")),
                         sm=Depends(get_sessionmaker)):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationError("没有可修改字段")
    if "price" in changes and ({"title", "status"} & set(changes)):
        raise ValidationError("售价与 Listing 内容请分开提交（两种审批动作）")
    action_type = "pricing.update_price" if "price" in changes else "product.update_listing"
    digest = hashlib.sha256(
        json.dumps({"shop": ctx.shop_id, "sku": sku, "action": action_type,
                    "changes": changes}, sort_keys=True, default=str).encode()).hexdigest()[:24]
    submission = OperationCreate(
        action_type=action_type, target_id=sku, after=changes,
        idempotency_key=f"patch-{sku}-{action_type.split('.')[-1]}-{digest}",
        reason=f"PATCH /products/{sku}",
    )
    data = await operation_submission.create_submission(
        sm, ctx, submission, request_id=get_request_id(request))
    return {"ok": True, "data": data}
