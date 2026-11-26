# -*- coding: utf-8 -*-
"""阶段 4 广告盾测试：规则、巡检、审核状态、告警通知、API。"""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from crossborder_ops.integrations.meta import build_meta_client
from crossborder_ops.integrations.meta.errors import (MetaAuthError, MetaPermissionError,
                                                      MetaRateLimited, MetaServerError)
from crossborder_ops.repositories import ads as ads_repo
from crossborder_ops.services import ad_shield_patrol, notifications
from crossborder_ops.services import ad_shield_rules as rules
from tests.conftest import auth

# ---------------- 规则 ----------------
def test_cvr_drop_rule():
    signals = rules.evaluate_cvr("ad_1", "2026-03-03", cvr_today=0.01, cvr_avg7=0.05)
    assert signals and signals[0].rule_code == "R005_CVR_DROP"
    assert signals[0].severity == "warn"


def test_account_status_rules():
    assert rules.evaluate_account_status("act", "w", 1) == []
    disabled = rules.evaluate_account_status("act", "w", 2)
    assert disabled[0].rule_code == "R006_ACCOUNT_DISABLED"
    assert "不等于封号" in disabled[0].detail["note"]


def test_meta_error_classification():
    cases = {
        "auth": (MetaAuthError("401"), "R401_TOKEN_INVALID"),
        "permission": (MetaPermissionError("403"), "R403_PERMISSION"),
        "rate_limited": (MetaRateLimited("429"), "R429_RATE_LIMIT"),
        "server": (MetaServerError("500"), "R5XX_PLATFORM"),
    }
    for kind, (exc, expected) in cases.items():
        assert rules.classify_meta_error(exc) == expected
        signal = rules.signal_from_meta_error("act", "w", exc)
        assert signal.rule_code == expected


def test_daily_totals_and_baseline():
    rows = [
        {"date": date(2026, 3, 1), "impressions": 100, "clicks": 10, "spend": 5,
         "conversions": 2, "revenue": 20},
        {"date": date(2026, 3, 2), "impressions": 100, "clicks": 10, "spend": 5,
         "conversions": 2, "revenue": 20},
        {"date": date(2026, 3, 3), "impressions": 100, "clicks": 10, "spend": 5,
         "conversions": 2, "revenue": 20},
    ]
    totals = rules.daily_totals(rows)
    assert totals["2026-03-01"]["clicks"] == 10
    assert rules.baseline_avg(totals, "2026-03-03", "spend") == pytest.approx(5.0)
    assert rules.ratio_baseline(totals, "2026-03-03", "clicks", "impressions") == pytest.approx(0.1)


# ---------------- 巡检 ----------------
async def test_patrol_records_reviews_and_dedupes(sessionmaker_):
    client = build_meta_client(None)
    first = await ad_shield_patrol.run_patrol(sessionmaker_, "S2", client,
                                              today=date(2026, 3, 3))
    assert first["source"] == "mock"
    assert first["accounts"] == 2
    assert first["reviews"] > 0
    assert first["created_events"] == 2          # 拒审（有原因）+ 审核异常（无原因）
    assert first["alerts"]["sent"] >= 2

    async with sessionmaker_() as session:
        reviews = await ads_repo.list_reviews(session, "S2")
    assert reviews
    assert any(r.manual_required for r in reviews)     # 无原因 → 待人工核实

    second = await ad_shield_patrol.run_patrol(sessionmaker_, "S2", client,
                                               today=date(2026, 3, 3))
    assert second["created_events"] == 0               # 同窗口重复检测被抑制
    async with sessionmaker_() as session:
        reviews_after = await ads_repo.list_reviews(session, "S2")
    assert len(reviews_after) == len(reviews)          # 审核状态 upsert 幂等


async def test_patrol_does_not_ban_on_spend_drop(sessionmaker_):
    """花费下降只出 warn，且 detail 明确"不等于封号"。"""
    signals = rules.evaluate_spend("S2", "act_x", "2026-03-05", spend_today=0, spend_avg7=100)
    assert signals[0].severity == "warn"
    assert "不等于封号" in signals[0].detail["note"]


# ---------------- 通知 ----------------
async def test_webhook_notifier_marks_alerts_sent(sessionmaker_):
    client = build_meta_client(None)
    await ad_shield_patrol.run_patrol(sessionmaker_, "S2", client,
                                      today=date(2026, 3, 6), deliver=False)
    seen: list[dict] = []
    transport = httpx.MockTransport(
        lambda request: (seen.append({"url": str(request.url)}), httpx.Response(200, json={"ok": True}))[1])
    notifier = notifications.WebhookNotifier("https://hook.test/alerts", transport=transport)
    result = await notifications.deliver_pending(sessionmaker_(), "S2", notifier=notifier)
    assert result["channel"] == "webhook"
    assert result["sent"] >= 1 and seen


async def test_notifier_failure_marks_failed_not_crash(sessionmaker_):
    client = build_meta_client(None)
    await ad_shield_patrol.run_patrol(sessionmaker_, "S2", client,
                                      today=date(2026, 3, 7), deliver=False)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    notifier = notifications.WebhookNotifier("https://hook.test/alerts",
                                             transport=httpx.MockTransport(boom))
    result = await notifications.deliver_pending(sessionmaker_(), "S2", notifier=notifier)
    assert result["failed"] >= 1

    from crossborder_ops.models import Alert
    from sqlalchemy import select
    async with sessionmaker_() as session:
        rows = list((await session.execute(
            select(Alert).where(Alert.shop_id == "S2", Alert.status == "failed"))).scalars().all())
    assert rows


# ---------------- API ----------------
async def test_patrol_api_admin_only(api, two_shops):
    forbidden = await api.post("/api/v1/ad-shield/patrol", headers=auth(two_shops["viewer"]))
    assert forbidden.status_code == 403

    ok = await api.post("/api/v1/ad-shield/patrol", headers=auth(two_shops["S1"]))
    assert ok.status_code == 200
    assert ok.json()["data"]["source"] == "mock"

    reviews = await api.get("/api/v1/ad-shield/reviews", headers=auth(two_shops["S1"]))
    assert reviews.status_code == 200
    assert "items" in reviews.json()["data"]
