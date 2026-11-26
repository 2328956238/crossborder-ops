"""广告域与广告盾仓储：所有查询强制 shop_id。"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Ad, AdAccount, AdCampaign, AdInsight, AdReview, AdSet, Alert, RiskEvent)


# ---------------- 广告账户 / 结构 ----------------
async def list_accounts(session: AsyncSession, shop_id: str) -> list[AdAccount]:
    return list((await session.execute(
        select(AdAccount).where(AdAccount.shop_id == shop_id).order_by(AdAccount.external_id)
    )).scalars().all())


async def create_account(session: AsyncSession, shop_id: str, **kwargs) -> AdAccount:
    kwargs.setdefault("id", str(uuid.uuid4()))
    account = AdAccount(shop_id=shop_id, **kwargs)
    session.add(account)
    await session.flush()
    return account


async def upsert_account(session: AsyncSession, shop_id: str, data: dict):
    existing = (await session.execute(
        select(AdAccount).where(AdAccount.shop_id == shop_id,
                                AdAccount.platform == data.get("platform", "meta"),
                                AdAccount.external_id == data["external_id"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        return existing
    return await create_account(session, shop_id, **data)


async def upsert_campaign(session: AsyncSession, shop_id: str, account_id: str, data: dict):
    existing = (await session.execute(
        select(AdCampaign).where(AdCampaign.account_id == account_id,
                                 AdCampaign.external_id == data["external_id"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        return existing
    campaign = AdCampaign(id=str(uuid.uuid4()), shop_id=shop_id, account_id=account_id, **data)
    session.add(campaign)
    await session.flush()
    return campaign


async def upsert_adset(session: AsyncSession, shop_id: str, campaign_id: str, data: dict):
    existing = (await session.execute(
        select(AdSet).where(AdSet.campaign_id == campaign_id,
                            AdSet.external_id == data["external_id"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        return existing
    row = AdSet(id=str(uuid.uuid4()), shop_id=shop_id, campaign_id=campaign_id, **data)
    session.add(row)
    await session.flush()
    return row


async def upsert_ad(session: AsyncSession, shop_id: str, adset_id: str, data: dict):
    existing = (await session.execute(
        select(Ad).where(Ad.adset_id == adset_id,
                         Ad.external_id == data["external_id"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        return existing
    row = Ad(id=str(uuid.uuid4()), shop_id=shop_id, adset_id=adset_id, **data)
    session.add(row)
    await session.flush()
    return row


async def list_campaigns(session: AsyncSession, shop_id: str, limit: int = 100) -> list[AdCampaign]:
    return list((await session.execute(
        select(AdCampaign).where(AdCampaign.shop_id == shop_id)
        .order_by(AdCampaign.external_id).limit(limit))).scalars().all())


async def list_adsets(session: AsyncSession, shop_id: str, limit: int = 100) -> list[AdSet]:
    return list((await session.execute(
        select(AdSet).where(AdSet.shop_id == shop_id).order_by(AdSet.external_id)
        .limit(limit))).scalars().all())


async def list_ads(session: AsyncSession, shop_id: str, limit: int = 100) -> list[Ad]:
    return list((await session.execute(
        select(Ad).where(Ad.shop_id == shop_id).order_by(Ad.external_id)
        .limit(limit))).scalars().all())


# ---------------- insights ----------------
async def upsert_insight(session: AsyncSession, shop_id: str, data: dict) -> AdInsight:
    """按 (shop, level, entity, date) 幂等写入。"""
    existing = (await session.execute(
        select(AdInsight).where(AdInsight.shop_id == shop_id,
                                AdInsight.level == data["level"],
                                AdInsight.entity_external_id == data["entity_external_id"],
                                AdInsight.date == data["date"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            if key not in ("level", "entity_external_id", "date"):
                setattr(existing, key, value)
        return existing
    row = AdInsight(shop_id=shop_id, **data)
    session.add(row)
    await session.flush()
    return row


async def list_insights(session: AsyncSession, shop_id: str, *, date_from: date,
                        date_to: date, level: str | None = None) -> list[AdInsight]:
    q = select(AdInsight).where(AdInsight.shop_id == shop_id,
                                AdInsight.date >= date_from, AdInsight.date <= date_to)
    if level:
        q = q.where(AdInsight.level == level)
    return list((await session.execute(q.order_by(AdInsight.date))).scalars().all())


# ---------------- 广告盾 ----------------
async def upsert_review(session: AsyncSession, shop_id: str, data: dict) -> AdReview:
    existing = (await session.execute(
        select(AdReview).where(AdReview.shop_id == shop_id,
                               AdReview.ad_id == data["ad_id"],
                               AdReview.fetched_at == data["fetched_at"]))).scalar_one_or_none()
    if existing:
        for key, value in data.items():
            setattr(existing, key, value)
        return existing
    row = AdReview(shop_id=shop_id, **data)
    session.add(row)
    await session.flush()
    return row


async def list_reviews(session: AsyncSession, shop_id: str, limit: int = 100) -> list[AdReview]:
    return list((await session.execute(
        select(AdReview).where(AdReview.shop_id == shop_id)
        .order_by(AdReview.id.desc()).limit(limit))).scalars().all())


async def insert_risk_event(session: AsyncSession, shop_id: str, data: dict) -> RiskEvent | None:
    """(shop, rule, entity, window) 唯一：重复检测返回 None，天然抑制重复告警。"""
    existing = (await session.execute(
        select(RiskEvent).where(RiskEvent.shop_id == shop_id,
                                RiskEvent.rule_code == data["rule_code"],
                                RiskEvent.entity_type == data["entity_type"],
                                RiskEvent.entity_id == data["entity_id"],
                                RiskEvent.window_key == data["window_key"]))).scalar_one_or_none()
    if existing:
        return None
    event = RiskEvent(id=data.pop("id", str(uuid.uuid4())), shop_id=shop_id, **data)
    session.add(event)
    await session.flush()
    return event


async def list_risk_events(session: AsyncSession, shop_id: str, *, status: str | None = None,
                           limit: int = 100) -> list[RiskEvent]:
    q = select(RiskEvent).where(RiskEvent.shop_id == shop_id)
    if status:
        q = q.where(RiskEvent.status == status)
    return list((await session.execute(
        q.order_by(RiskEvent.id.desc()).limit(limit))).scalars().all())


async def get_risk_event(session: AsyncSession, shop_id: str, event_id: str) -> RiskEvent | None:
    return (await session.execute(
        select(RiskEvent).where(RiskEvent.shop_id == shop_id,
                                RiskEvent.id == event_id))).scalar_one_or_none()


async def set_risk_status(session: AsyncSession, event: RiskEvent, status: str, actor: str) -> RiskEvent:
    event.status = status
    if status == "acknowledged":
        event.acked_by = actor
    elif status == "resolved":
        event.resolved_by = actor
    return event


async def insert_alert(session: AsyncSession, shop_id: str, data: dict) -> Alert | None:
    existing = (await session.execute(
        select(Alert).where(Alert.dedupe_key == data["dedupe_key"]))).scalar_one_or_none()
    if existing:
        return None
    alert = Alert(shop_id=shop_id, **data)
    session.add(alert)
    await session.flush()
    return alert


async def list_alerts(session: AsyncSession, shop_id: str, limit: int = 100) -> list[Alert]:
    return list((await session.execute(
        select(Alert).where(Alert.shop_id == shop_id)
        .order_by(Alert.id.desc()).limit(limit))).scalars().all())
