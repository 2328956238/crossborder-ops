"""Operation API：查询 / 审批 / 拒绝 / 执行（shop_id 只来自认证上下文）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from ...core.errors import ApprovalError
from ...core.security import ShopContext
from ...db import get_sessionmaker
from ...services import approval as approval_service
from ..deps import get_auth_context, get_local_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

_CODE_TO_STATUS = {"not_found": 404, "forbidden_shop": 403, "invalid_arg": 422,
                   "unknown_action": 422}


def _raise_for(exc: ApprovalError) -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=_CODE_TO_STATUS.get(exc.code, 400),
                        detail={"code": exc.code, "message": exc.message})


@router.get("")
async def list_ops(status: str | None = Query(default=None),
                   limit: int = Query(default=50, ge=1, le=200),
                   ctx: ShopContext = Depends(get_auth_context),
                   sm=Depends(get_sessionmaker)):
    try:
        items = await approval_service.list_operations(sm, shop_id=ctx.shop_id,
                                                       status=status, limit=limit)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.get("/{operation_id}")
async def get_op(operation_id: str, ctx: ShopContext = Depends(get_auth_context),
                 sm=Depends(get_sessionmaker)):
    try:
        data = await approval_service.get_operation(sm, operation_id, shop_id=ctx.shop_id)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": data}


@router.post("/{operation_id}/approve")
async def approve_op(operation_id: str, ctx: ShopContext = Depends(get_auth_context),
                     sm=Depends(get_sessionmaker)):
    try:
        result = await approval_service.approve_operation(
            sm, operation_id, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": {"operation_id": operation_id, "result": result}}


@router.post("/{operation_id}/reject")
async def reject_op(operation_id: str, ctx: ShopContext = Depends(get_auth_context),
                    sm=Depends(get_sessionmaker)):
    try:
        result = await approval_service.reject_operation(
            sm, operation_id, shop_id=ctx.shop_id, actor=ctx.actor)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": {"operation_id": operation_id, "result": result}}


@router.post("/{operation_id}/execute")
async def execute_op(operation_id: str, ctx: ShopContext = Depends(get_auth_context),
                     sm=Depends(get_sessionmaker),
                     data=Depends(get_local_data)):
    try:
        result = await approval_service.execute_operation(
            sm, operation_id, shop_id=ctx.shop_id, data=data)
        detail = await approval_service.get_operation(sm, operation_id, shop_id=ctx.shop_id)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": {"operation_id": operation_id, "result": result,
                                 "operation": detail}}
