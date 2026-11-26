"""平台凭证仓储：密文存库，读取时解密由 service 负责。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ShopCredential


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_credential(session: AsyncSession, shop_id: str, provider: str) -> ShopCredential | None:
    return (await session.execute(
        select(ShopCredential).where(ShopCredential.shop_id == shop_id,
                                     ShopCredential.provider == provider))).scalar_one_or_none()


async def upsert_credential(session: AsyncSession, *, shop_id: str, provider: str,
                            access_token_encrypted: str, token_type: str = "bearer",
                            scopes: str = "", expires_at: str | None = None) -> ShopCredential:
    record = await get_credential(session, shop_id, provider)
    if record is None:
        record = ShopCredential(shop_id=shop_id, provider=provider,
                                access_token_encrypted=access_token_encrypted,
                                token_type=token_type, scopes=scopes,
                                expires_at=expires_at, updated_at=_now())
        session.add(record)
    else:
        record.access_token_encrypted = access_token_encrypted
        record.token_type = token_type
        record.scopes = scopes
        record.expires_at = expires_at
        record.updated_at = _now()
    await session.flush()
    return record
