"""Meta OAuth：授权链接、code 换 token、长期 token、加密存储与过期检查。"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core import crypto
from ...core.errors import AppError, ValidationError
from ...repositories import credentials as cred_repo
from .errors import MetaAuthError, MetaConfigError
from .errors import MetaError

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://graph.facebook.com/{version}/oauth/access_token"
REFRESH_THRESHOLD_SECONDS = 7 * 24 * 3600


def authorize_url(*, state: str, scopes: str | None = None) -> str:
    settings = get_settings()
    if not settings.meta_app_id:
        raise MetaConfigError("缺少 META_APP_ID")
    scope = scopes or "ads_read,ads_management,business_management"
    return (f"https://www.facebook.com/{settings.meta_api_version}/dialog/oauth"
            f"?client_id={settings.meta_app_id}"
            f"&redirect_uri={settings.meta_redirect_uri}"
            f"&state={state}&scope={scope}")


async def exchange_code(code: str, *, transport: httpx.AsyncBaseTransport | None = None
                        ) -> dict[str, Any]:
    """授权码换短期 token。"""
    settings = get_settings()
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise MetaConfigError("缺少 META_APP_ID / META_APP_SECRET")
    params = {"client_id": settings.meta_app_id, "client_secret": settings.meta_app_secret,
              "redirect_uri": settings.meta_redirect_uri, "code": code}
    return await _token_request(params, transport=transport)


async def exchange_long_lived(short_token: str, *,
                              transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """短期 token 换长期 token（60 天）。"""
    settings = get_settings()
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise MetaConfigError("缺少 META_APP_ID / META_APP_SECRET")
    params = {"grant_type": "fb_exchange_token", "client_id": settings.meta_app_id,
              "client_secret": settings.meta_app_secret,
              "fb_exchange_token": short_token}
    return await _token_request(params, transport=transport)


async def _token_request(params: dict[str, str], *,
                         transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    settings = get_settings()
    url = TOKEN_ENDPOINT.format(version=settings.meta_api_version)
    try:
        async with httpx.AsyncClient(timeout=settings.meta_timeout_seconds,
                                     transport=transport) as http:
            response = await http.get(url, params=params)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise MetaError(f"OAuth 网络异常: {type(exc).__name__}") from exc
    payload = response.json() if response.content else {}
    if response.status_code != 200 or "access_token" not in payload:
        raise MetaAuthError(f"OAuth 换取 token 失败: {str(payload)[:200]}",
                            status=response.status_code)
    return payload


def expires_at_from(payload: dict[str, Any]) -> str | None:
    expires_in = payload.get("expires_in")
    if not expires_in:
        return None
    ts = time.time() + int(expires_in)
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


async def save_token(session: AsyncSession, shop_id: str, payload: dict[str, Any]) -> dict:
    token = payload.get("access_token", "")
    if not token:
        raise ValidationError("token payload 缺少 access_token")
    record = await cred_repo.upsert_credential(
        session, shop_id=shop_id, provider="meta",
        access_token_encrypted=crypto.encrypt(token),
        token_type=payload.get("token_type", "bearer"),
        expires_at=expires_at_from(payload))
    return {"shop_id": shop_id, "provider": "meta",
            "token_masked": crypto.mask(token),
            "expires_at": record.expires_at}


async def load_token(session: AsyncSession, shop_id: str) -> str | None:
    record = await cred_repo.get_credential(session, shop_id, "meta")
    if record is None:
        return None
    return crypto.decrypt(record.access_token_encrypted)


async def needs_refresh(session: AsyncSession, shop_id: str) -> bool:
    record = await cred_repo.get_credential(session, shop_id, "meta")
    if record is None or not record.expires_at:
        return False
    try:
        expires = datetime.fromisoformat(record.expires_at)
    except ValueError:
        return True
    return (expires - datetime.now(timezone.utc)).total_seconds() < REFRESH_THRESHOLD_SECONDS


async def refresh_if_needed(session: AsyncSession, shop_id: str, *,
                            transport: httpx.AsyncBaseTransport | None = None) -> str | None:
    token = await load_token(session, shop_id)
    if token is None:
        return None
    if not await needs_refresh(session, shop_id):
        return token
    payload = await exchange_long_lived(token, transport=transport)
    await save_token(session, shop_id, payload)
    return payload["access_token"]


__all__ = ["authorize_url", "exchange_code", "exchange_long_lived", "save_token", "load_token",
           "needs_refresh", "refresh_if_needed", "AppError"]
