"""广告盾巡检：账户状态 → 广告审核状态 → Insights 指标异常 → 风险事件 → 告警。

设计要点：
- 只做"检测 + 记录 + 告警"，不自动改账户/广告（写操作必须走审批链）；
- 花费下降、花费为 0 都不直接判封号，统一按 warn + 人工核实；
- 401/403/429/5xx 各自成规则，绝不含并；
- 无法获取审核原因时必须 manual_required=True。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..integrations.meta import accounts as meta_accounts
from ..integrations.meta import ads as meta_ads
from ..integrations.meta import adsets as meta_adsets
from ..integrations.meta import campaigns as meta_campaigns
from ..integrations.meta import insights as meta_insights
from ..repositories import ads as repo
from . import ad_shield as shield
from . import ad_shield_rules as rules
from . import notifications

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source(client) -> str:
    return "mock" if getattr(client, "is_mock", False) else "meta"


def _reason(issues: list[dict] | None) -> tuple[str | None, str | None]:
    if not issues:
        return None, None
    first = issues[0] or {}
    return (str(first.get("error_code")) if first.get("error_code") is not None else None,
            first.get("error_summary") or first.get("error_message"))


async def run_patrol(sm: SessionFactory, shop_id: str, client, *,
                     today: date | None = None, deliver: bool = True,
                     notifier=None) -> dict:
    window = (today or datetime.now(timezone.utc).date()).isoformat()
    stats = {"shop_id": shop_id, "window": window, "source": _source(client),
             "accounts": 0, "reviews": 0, "insights": 0, "signals": 0,
             "created_events": 0, "alerts": None, "errors": []}
    signals: list[rules.Signal] = []
    review_rows: list[dict] = []
    insight_rows: list[dict] = []

    try:
        accounts = await meta_accounts.list_accounts(client)
    except Exception as exc:  # noqa: BLE001 - 分类后继续
        stats["errors"].append(type(exc).__name__)
        accounts = []
        signals.append(rules.signal_from_meta_error("unknown", window, exc))

    for account in accounts:
        account_id = account.get("id", "unknown")
        stats["accounts"] += 1
        signals += rules.evaluate_account_status(account_id, window,
                                                 account.get("account_status"))

        # ---- 广告审核状态 ----
        try:
            campaigns = await meta_campaigns.list_campaigns(client, account_id)
        except Exception as exc:  # noqa: BLE001
            campaigns = []
            stats["errors"].append(type(exc).__name__)
            signals.append(rules.signal_from_meta_error(account_id, window, exc))

        for campaign in campaigns:
            try:
                adsets = await meta_adsets.list_adsets(client, campaign["id"])
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append(type(exc).__name__)
                continue
            for adset in adsets:
                try:
                    ads = await meta_ads.list_ads_with_review(client, adset["id"])
                except Exception as exc:  # noqa: BLE001
                    stats["errors"].append(type(exc).__name__)
                    continue
                for ad in ads:
                    reason_code, reason_text = _reason(ad.get("issues_info"))
                    status = str(ad.get("effective_status") or ad.get("status") or "UNKNOWN")
                    manual_required = not (reason_code or reason_text)
                    review_rows.append({
                        "ad_id": ad["id"], "status": status,
                        "reason_code": reason_code, "reason_text": reason_text,
                        "manual_required": manual_required, "fetched_at": window,
                    })
                    stats["reviews"] += 1
                    signals += rules.evaluate_review(shop_id, ad["id"], window,
                                                     status=status, reason_code=reason_code,
                                                     reason_text=reason_text)

        # ---- Insights 异常 ----
        try:
            rows = await meta_insights.fetch_insights(
                client, account_id, since=date.fromisoformat(window) - timedelta(days=7),
                until=date.fromisoformat(window))
        except Exception as exc:  # noqa: BLE001
            rows = []
            stats["errors"].append(type(exc).__name__)
            signals.append(rules.signal_from_meta_error(account_id, window, exc))

        stats["insights"] += len(rows)
        for row in rows:
            row["source"] = _source(client)
            row["entity_external_id"] = account_id
            insight_rows.append(row)

        totals = rules.daily_totals(rows)
        current = totals.get(window)
        if current:
            spend_avg = rules.baseline_avg(totals, window, "spend")
            if spend_avg:
                signals += rules.evaluate_spend(shop_id, account_id, window,
                                                spend_today=current["spend"],
                                                spend_avg7=spend_avg)
            ctr_today = (current["clicks"] / current["impressions"]) if current["impressions"] else None
            signals += rules.evaluate_ctr(shop_id, account_id, window, ctr_today=ctr_today,
                                          ctr_avg7=rules.ratio_baseline(totals, window, "clicks",
                                                                        "impressions"))
            cvr_today = (current["conversions"] / current["clicks"]) if current["clicks"] else None
            signals += rules.evaluate_cvr(account_id, window, cvr_today=cvr_today,
                                          cvr_avg7=rules.ratio_baseline(totals, window,
                                                                        "conversions", "clicks"))
            cpa_today = (current["spend"] / current["conversions"]) if current["conversions"] else None
            signals += rules.evaluate_cpa(shop_id, account_id, window, cpa_today=cpa_today,
                                          cpa_avg7=rules.ratio_baseline(totals, window, "spend",
                                                                        "conversions"))

    # ---- 持久化（独立事务：外部数据已拉完，避免长事务） ----
    async with sm() as session:
        async with session.begin():
            for row in review_rows:
                await repo.upsert_review(session, shop_id, row)
            for row in insight_rows:
                await repo.upsert_insight(session, shop_id, row)
            created = await shield.record_signals(session, shop_id, signals)

    stats["signals"] = len(signals)
    stats["created_events"] = len(created)

    if deliver:
        async with sm() as session:
            stats["alerts"] = await notifications.deliver_pending(session, shop_id,
                                                                  notifier=notifier)
    return stats


async def patrol_all_shops(sm: SessionFactory, *, today: date | None = None) -> list[dict]:
    """定时任务入口：遍历所有店铺；每店用自己的凭证（没有就走 Mock）。"""
    from ..integrations.meta import build_meta_client
    from ..integrations.meta import oauth as meta_oauth
    from ..repositories import business as repo

    results = []
    async with sm() as session:
        shops = await repo.list_shops(session)
        shop_ids = [s.id for s in shops]
    for shop_id in shop_ids:
        async with sm() as session:
            token = await meta_oauth.load_token(session, shop_id)
        client = build_meta_client(token)
        try:
            results.append(await run_patrol(sm, shop_id, client, today=today))
        except Exception as exc:  # noqa: BLE001 - 单店失败不影响其它店
            logger.exception("广告盾巡检失败 shop=%s", shop_id)
            results.append({"shop_id": shop_id, "error": type(exc).__name__})
    return results
