"""Meta 集成路由：状态/账户读 viewer+；OAuth 与同步按权限分级并审计（不记录 token 原文）。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core import audit as audit_core
from ...core.permissions import require_role
from ...core.security import ShopContext
from ...db import get_session
from ...db import get_sessionmaker
from ...integrations import meta as meta_integration
from ...integrations.meta import oauth as meta_oauth
from ...services import meta_sync
from ..deps import get_request_id

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


class OAuthState(BaseModel):
    state: str = Field(min_length=4, max_length=128)


class OAuthExchange(BaseModel):
    code: str = Field(min_length=4, max_length=2048)


class SyncRequest(BaseModel):
    since: date
    until: date


@router.get("/status")
async def status(ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    return {"ok": True, "data": meta_integration.meta_status()}


@router.post("/oauth/authorize-url")
async def authorize_url(payload: OAuthState, request: Request,
                        ctx: ShopContext = Depends(require_role("admin")),
                        sm=Depends(get_sessionmaker)):
    try:
        url = meta_oauth.authorize_url(state=payload.state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail={"code": "meta_config_error",
                                                     "message": str(exc)}) from exc
    async with sm() as session:
        async with session.begin():
            await audit_core.record(
                session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
                action="meta.oauth.authorize_url", entity_type="shop_credential",
                entity_id="meta", before=None, after={"state": payload.state},
                request_id=get_request_id(request))
    return {"ok": True, "data": {"authorize_url": url}}


@router.post("/oauth/exchange")
async def exchange(payload: OAuthExchange, request: Request,
                   session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(require_role("admin"))):
    try:
        token_payload = await meta_oauth.exchange_code(payload.code)
        if token_payload.get("expires_in"):
            token_payload = await meta_oauth.exchange_long_lived(token_payload["access_token"])
        saved = await meta_oauth.save_token(session, ctx.shop_id, token_payload)
    except Exception as exc:  # noqa: BLE001 - 不把 token/secret 泄露进错误响应
        raise HTTPException(status_code=400, detail={"code": "meta_oauth_failed",
                                                     "message": type(exc).__name__}) from exc
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="meta.oauth.exchange", entity_type="shop_credential", entity_id="meta",
        before=None, after={"token_masked": saved["token_masked"],
                            "expires_at": saved["expires_at"]},
        request_id=get_request_id(request))
    return {"ok": True, "data": saved}


@router.get("/accounts")
async def live_accounts(session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(require_role("viewer", "operator", "admin"))):
    token = await meta_oauth.load_token(session, ctx.shop_id)
    client = meta_integration.build_meta_client(token)
    from ...integrations.meta.accounts import list_accounts

    return {"ok": True, "data": {"source": "mock" if client.is_mock else "meta",
                                 "items": await list_accounts(client)}}


@router.post("/sync")
async def sync(payload: SyncRequest, request: Request,
               session: AsyncSession = Depends(get_session),
               ctx: ShopContext = Depends(require_role("operator", "admin"))):
    token = await meta_oauth.load_token(session, ctx.shop_id)
    client = meta_integration.build_meta_client(token)
    result = await meta_sync.sync_all(session, ctx, client,
                                      since=payload.since, until=payload.until)
    await audit_core.record(
        session, shop_id=ctx.shop_id, actor=ctx.actor, role=ctx.role,
        action="meta.sync", entity_type="meta", entity_id=ctx.shop_id,
        before=None, after=result, request_id=get_request_id(request))
    return {"ok": True, "data": result}
