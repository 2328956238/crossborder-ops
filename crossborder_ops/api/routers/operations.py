"""审批路由：创建（DRAFT）→ 提交（PENDING）→ 审批/拒绝 → 执行；全程审计。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request

from ...core import audit as audit_core
from ...core.errors import ApprovalError
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_sessionmaker
from ...schemas.operations import OperationCreate, OperationSubmit
from ...services import approval as approval_service
from ...services import operation_execution, operation_submission
from ..deps import get_request_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

_CODE_TO_STATUS = {"not_found": 404, "forbidden_shop": 403, "invalid_arg": 422,
                   "unknown_action": 422}


def _raise_for(exc: ApprovalError) -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=_CODE_TO_STATUS.get(exc.code, 400),
                        detail={"code": exc.code, "message": exc.message})


async def _audit_transition(sm, ctx: ShopContext, op_id: str, action: str,
                            before: dict, after: dict, request_id: str | None,
                            result: str = "ok", failure_reason: str | None = None) -> None:
    async with sm() as session:
        async with session.begin():
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action=action, entity_type="operation", entity_id=op_id,
                before=before, after=after, request_id=request_id,
                operation_id=op_id, result=result, failure_reason=failure_reason)


@router.get("")
async def list_ops(status: str | None = Query(default=None),
                   limit: int = Query(default=50, ge=1, le=200),
                   ctx: ShopContext = Depends(require_role("viewer", "operator", "admin")),
                   sm=Depends(get_sessionmaker)):
    try:
        items = await approval_service.list_operations(sm, shop_id=ctx.shop_id,
                                                       status=status, limit=limit)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": {"shop_id": ctx.shop_id, "items": items, "count": len(items)}}


@router.post("", status_code=201)
async def create_operation(payload: OperationCreate, request: Request,
                           ctx: ShopContext = Depends(require_role("operator", "admin")),
                           sm=Depends(get_sessionmaker)):
    try:
        data = await operation_submission.create_submission(
            sm, ctx, payload, request_id=get_request_id(request))
    except Exception as exc:  # noqa: BLE001
        from ...db import get_sessionmaker

        await audit_core.record_failure_for_request(
            get_sessionmaker(), ctx=ctx, request_id=get_request_id(request),
            action="operation.create", entity_type="operation",
            entity_id=payload.target_id, exc=exc)
        raise
    return {"ok": True, "data": data}


@router.get("/{operation_id}")
async def get_op(operation_id: str,
                 ctx: ShopContext = Depends(require_role("viewer", "operator", "admin")),
                 sm=Depends(get_sessionmaker)):
    try:
        data = await approval_service.get_operation(sm, operation_id, shop_id=ctx.shop_id)
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": data}


@router.post("/{operation_id}/submit")
async def submit_op(operation_id: str, payload: OperationSubmit, request: Request,
                    ctx: ShopContext = Depends(require_role("operator", "admin")),
                    sm=Depends(get_sessionmaker)):
    result = await operation_submission.submit_operation(
        sm, ctx, operation_id, request_id=get_request_id(request))
    return {"ok": True, "data": result}


@router.post("/{operation_id}/approve")
async def approve_op(operation_id: str, request: Request,
                     ctx: ShopContext = Depends(require_role("operator", "admin")),
                     sm=Depends(get_sessionmaker)):
    op = await approval_service.get_operation(sm, operation_id, shop_id=ctx.shop_id)
    # 审批时重新检查目标对象（存在性 + 归属）
    await operation_submission.ensure_target_exists(sm, ctx, op)
    try:
        result = await approval_service.approve_operation(
            sm, operation_id, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role)
    except ApprovalError as exc:
        _raise_for(exc)
    await _audit_transition(sm, ctx, operation_id, "operation.approve",
                            {"status": op["status"]},
                            {"status": "APPROVED" if result == "approved" else result},
                            get_request_id(request),
                            result="ok" if result == "approved" else "failed",
                            failure_reason=None if result == "approved" else result)
    return {"ok": True, "data": {"operation_id": operation_id, "result": result}}


@router.post("/{operation_id}/reject")
async def reject_op(operation_id: str, request: Request,
                    ctx: ShopContext = Depends(require_role("operator", "admin")),
                    sm=Depends(get_sessionmaker)):
    op = await approval_service.get_operation(sm, operation_id, shop_id=ctx.shop_id)
    try:
        result = await approval_service.reject_operation(
            sm, operation_id, shop_id=ctx.shop_id, actor=ctx.actor)
    except ApprovalError as exc:
        _raise_for(exc)
    await _audit_transition(sm, ctx, operation_id, "operation.reject",
                            {"status": op["status"]},
                            {"status": "REJECTED" if result == "rejected" else result},
                            get_request_id(request),
                            result="ok" if result == "rejected" else "failed",
                            failure_reason=None if result == "rejected" else result)
    return {"ok": True, "data": {"operation_id": operation_id, "result": result}}


@router.post("/{operation_id}/execute")
async def execute_op(operation_id: str, request: Request,
                     ctx: ShopContext = Depends(require_role("operator", "admin")),
                     sm=Depends(get_sessionmaker)):
    try:
        data = await operation_execution.execute(
            sm, ctx, operation_id, request_id=get_request_id(request))
    except ApprovalError as exc:
        _raise_for(exc)
    return {"ok": True, "data": data}
