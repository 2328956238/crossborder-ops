"""广告盾风险规则（纯函数，独立于 API 路由与数据库）。

设计约束（来自需求）：
1. 不能仅凭广告花费下降就判定账户被封禁 → 花费下降只产生 warn，并要求人工核实；
2. 不能把 API 401 / 403 / 429 / 5xx 混为同一种账户风险 → 分别映射为不同 rule_code 与严重级：
   - 401：token 失效（critical，需重新授权）
   - 403：权限/账户受限（critical，需人工确认，不等于封号）
   - 429：限流（info，可恢复）
   - 5xx：平台故障（warn，可恢复，不是账户问题）
3. 无法从 API 获取审核原因时，必须标记 manual_required=True（待人工核实）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

EPS = 1e-9


@dataclass(frozen=True)
class Signal:
    rule_code: str
    severity: str
    entity_type: str
    entity_id: str
    window_key: str
    detail: dict = field(default_factory=dict)


def _ratio(current: Decimal | float, baseline: Decimal | float) -> float | None:
    base = float(baseline)
    if base <= EPS:
        return None
    return float(current) / base


def evaluate_spend(shop_id: str, account_id: str, window_key: str, *,
                   spend_today: Decimal | float, spend_avg7: Decimal | float) -> list[Signal]:
    """花费大幅下降：只提示核查（可能是停投/预算调整/审核拒绝），不判定封号。"""
    ratio = _ratio(spend_today, spend_avg7)
    if ratio is None or ratio >= 0.3:
        return []
    return [Signal(
        rule_code="R001_SPEND_DROP", severity="warn", entity_type="account",
        entity_id=account_id, window_key=window_key,
        detail={"spend_today": str(spend_today), "spend_avg7": str(spend_avg7),
                "ratio": round(ratio, 4),
                "note": "花费下降不等于封号，需核查预算/审核/停投"}),
    ]


def evaluate_ctr(shop_id: str, ad_id: str, window_key: str, *,
                 ctr_today: float | None, ctr_avg7: float | None) -> list[Signal]:
    if ctr_today is None or not ctr_avg7 or ctr_avg7 <= EPS:
        return []
    ratio = ctr_today / ctr_avg7
    if ratio >= 0.5:
        return []
    return [Signal(rule_code="R002_CTR_DROP", severity="warn", entity_type="ad",
                   entity_id=ad_id, window_key=window_key,
                   detail={"ctr_today": ctr_today, "ctr_avg7": ctr_avg7,
                           "ratio": round(ratio, 4)})]


def evaluate_cpa(shop_id: str, ad_id: str, window_key: str, *,
                 cpa_today: float | None, cpa_avg7: float | None) -> list[Signal]:
    if cpa_today is None or not cpa_avg7 or cpa_avg7 <= EPS:
        return []
    ratio = cpa_today / cpa_avg7
    if ratio <= 2.0:
        return []
    return [Signal(rule_code="R003_CPA_SPIKE", severity="warn", entity_type="ad",
                   entity_id=ad_id, window_key=window_key,
                   detail={"cpa_today": cpa_today, "cpa_avg7": cpa_avg7,
                           "ratio": round(ratio, 4)})]


API_ERROR_RULES = {
    401: ("R401_TOKEN_INVALID", "critical", "token 失效，需要重新授权"),
    403: ("R403_PERMISSION", "critical", "权限受限或账户受限，需人工确认（不等于封号）"),
    429: ("R429_RATE_LIMIT", "info", "触发平台限流，可退避重试"),
    500: ("R5XX_PLATFORM", "warn", "平台 5xx，属于平台故障"),
    503: ("R5XX_PLATFORM", "warn", "平台 5xx，属于平台故障"),
}


def evaluate_api_error(account_id: str, window_key: str, status_code: int) -> list[Signal]:
    rule = API_ERROR_RULES.get(status_code)
    if rule is None and 500 <= status_code < 600:
        rule = API_ERROR_RULES[500]
    if rule is None:
        return []
    code, severity, note = rule
    return [Signal(rule_code=code, severity=severity, entity_type="account",
                   entity_id=account_id, window_key=window_key,
                   detail={"http_status": status_code, "note": note})]


def evaluate_review(shop_id: str, ad_id: str, window_key: str, *,
                    status: str, reason_code: str | None,
                    reason_text: str | None) -> list[Signal]:
    if status.upper() not in {"REJECTED", "DISAPPROVED", "WITH_ISSUES"}:
        return []
    manual_required = not (reason_code or reason_text)
    return [Signal(rule_code="R004_REVIEW_REJECTED",
                   severity="critical" if not manual_required else "warn",
                   entity_type="ad", entity_id=ad_id, window_key=window_key,
                   detail={"status": status, "reason_code": reason_code,
                           "reason_text": reason_text,
                           "manual_required": manual_required})]


def collect(signals: list[Signal]) -> list[dict]:
    return [{"rule_code": s.rule_code, "severity": s.severity,
             "entity_type": s.entity_type, "entity_id": s.entity_id,
             "window_key": s.window_key, "detail": s.detail} for s in signals]


def ratio_baseline(totals: dict, today: str, numerator: str, denominator: str,
                   days: int = 7) -> float | None:
    """今天之前 N 天的日均比率（如 CTR/CVR/CPA），无数据返回 None。"""
    from datetime import date, timedelta

    today_date = date.fromisoformat(today)
    values = []
    for offset in range(1, days + 1):
        bucket = totals.get((today_date - timedelta(days=offset)).isoformat())
        if not bucket:
            continue
        denom = bucket[denominator]
        if denom:
            values.append(bucket[numerator] / denom)
    if not values:
        return None
    return sum(values) / len(values)


# ---------------- 账户状态 / 转化率 / 错误映射（阶段 4） ----------------
ACCOUNT_STATUS_RULES = {
    2: ("R006_ACCOUNT_DISABLED", "critical", "账户被禁用，需人工确认原因（不等于封号结论）"),
    3: ("R006_ACCOUNT_UNSETTLED", "warn", "账户有未结清款项，投放可能受限"),
    7: ("R006_ACCOUNT_PENDING_RISK_REVIEW", "warn", "账户处于风险审核中，需人工跟进"),
    9: ("R006_ACCOUNT_IN_GRACE_PERIOD", "warn", "账户宽限期，尽快处理"),
    100: ("R006_ACCOUNT_CLOSED", "critical", "账户已关闭"),
    201: ("R006_ACCOUNT_CLOSED", "critical", "账户已关闭"),
}


def evaluate_account_status(account_id: str, window_key: str, status_code) -> list[Signal]:
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return []
    rule = ACCOUNT_STATUS_RULES.get(code)
    if rule is None:
        return []
    rule_code, severity, note = rule
    return [Signal(rule_code=rule_code, severity=severity, entity_type="account",
                   entity_id=account_id, window_key=window_key,
                   detail={"account_status": code, "note": note})]


def evaluate_cvr(ad_id: str, window_key: str, *, cvr_today: float | None,
                 cvr_avg7: float | None) -> list[Signal]:
    if cvr_today is None or not cvr_avg7 or cvr_avg7 <= EPS:
        return []
    ratio = cvr_today / cvr_avg7
    if ratio >= 0.5:
        return []
    return [Signal(rule_code="R005_CVR_DROP", severity="warn", entity_type="ad",
                   entity_id=ad_id, window_key=window_key,
                   detail={"cvr_today": round(cvr_today, 6),
                           "cvr_avg7": round(cvr_avg7, 6), "ratio": round(ratio, 4)})]


def classify_meta_error(exc) -> str:
    """Meta 异常 → 广告盾 rule_code（不把所有错误都当账户风险）。"""
    return {
        "auth": "R401_TOKEN_INVALID",
        "permission": "R403_PERMISSION",
        "rate_limited": "R429_RATE_LIMIT",
        "server": "R5XX_PLATFORM",
        "network": "R_NETWORK_UNKNOWN",
        "config": "R_CONFIG_MISSING",
    }.get(getattr(exc, "kind", ""), "R_META_UNKNOWN")


def signal_from_meta_error(account_id: str, window_key: str, exc) -> Signal:
    code = classify_meta_error(exc)
    severity = {"R401_TOKEN_INVALID": "critical", "R403_PERMISSION": "critical",
                "R429_RATE_LIMIT": "info", "R5XX_PLATFORM": "warn",
                "R_NETWORK_UNKNOWN": "warn", "R_CONFIG_MISSING": "warn"}.get(code, "warn")
    return Signal(rule_code=code, severity=severity, entity_type="account",
                  entity_id=account_id, window_key=window_key,
                  detail={"error_kind": getattr(exc, "kind", "unknown"),
                          "status": getattr(exc, "status", None),
                          "note": "按错误类型分类，不代表账户被封禁"})


def daily_totals(rows: list) -> dict:
    totals: dict = {}
    for row in rows:
        day = row["date"] if isinstance(row, dict) else row.date
        key = str(day)
        bucket = totals.setdefault(key, {"impressions": 0, "clicks": 0, "spend": 0.0,
                                         "conversions": 0.0, "revenue": 0.0})
        bucket["impressions"] += int(row["impressions"])
        bucket["clicks"] += int(row["clicks"])
        bucket["spend"] += float(row["spend"])
        bucket["conversions"] += float(row["conversions"])
        bucket["revenue"] += float(row["revenue"])
    return totals


def baseline_avg(totals: dict, today: str, key: str, days: int = 7) -> float | None:
    from datetime import date, timedelta

    today_date = date.fromisoformat(today)
    values = []
    for offset in range(1, days + 1):
        day = (today_date - timedelta(days=offset)).isoformat()
        if day in totals:
            values.append(totals[day][key])
    if not values:
        return None
    return sum(values) / len(values)
