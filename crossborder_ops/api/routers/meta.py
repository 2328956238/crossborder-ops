"""Meta 集成路由：状态、OAuth、同步。没有真实凭证时明确走 Mock。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import ShopContext
from ...db import get_session
from ...integrations import meta as meta_integration
from ...integrations.meta import oauth as meta_oauth
from ...services import meta_sync
from ..deps import get_auth_context

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


class OAuthState(BaseModel):
    state: str = Field(min_length=4, max_length=128)


class OAuthExchange(BaseModel):
    code: str = Field(min_length=4, max_length=2048)


class SyncRequest(BaseModel):
    since: date
    until: date


@router.get("/status")
async def status(ctx: ShopContext = Depends(get_auth_context)):
    return {"ok": True, "data": meta_integration.meta_status()}


@router.post("/oauth/authorize-url")
async def authorize_url(payload: OAuthState, ctx: ShopContext = Depends(get_auth_context)):
    try:
        url = meta_oauth.authorize_url(state=payload.state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail={"code": "meta_config_error",
                                                     "message": str(exc)}) from exc
    return {"ok": True, "data": {"authorize_url": url}}


@router.post("/oauth/exchange")
async def exchange(payload: OAuthExchange, session: AsyncSession = Depends(get_session),
                   ctx: ShopContext = Depends(get_auth_context)):
    try:
        token_payload = await meta_oauth.exchange_code(payload.code)
        if token_payload.get("expires_in"):
            token_payload = await meta_oauth.exchange_long_lived(token_payload["access_token"])
        saved = await meta_oauth.save_token(session, ctx.shop_id, token_payload)
    except Exception as exc:  # noqa: BLE001 - 不把 token/secret 泄露进错误响应
        raise HTTPException(status_code=400, detail={"code": "meta_oauth_failed",
                                                     "message": type(exc).__name__}) from exc
    return {"ok": True, "data": saved}


@router.get("/accounts")
async def live_accounts(session: AsyncSession = Depends(get_session),
                        ctx: ShopContext = Depends(get_auth_context)):
    token = await meta_oauth.load_token(session, ctx.shop_id)
    client = meta_integration.build_meta_client(token)
    from ...integrations.meta.accounts import list_accounts

    return {"ok": True, "data": {"source": "mock" if client.is_mock else "meta",
                                 "items": await list_accounts(client)}}


@router.post("/sync")
async def sync(payload: SyncRequest, session: AsyncSession = Depends(get_session),
               ctx: ShopContext = Depends(get_auth_context)):
    token = await meta_oauth.load_token(session, ctx.shop_id)
    client = meta_integration.build_meta_client(token)
    result = await meta_sync.sync_all(session, ctx.shop_id, client,
                                      since=payload.since, until=payload.until)
    return {"ok": True, "data": result}
