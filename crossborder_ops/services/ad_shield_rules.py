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
