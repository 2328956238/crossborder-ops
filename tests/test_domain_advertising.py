"""S1 业务计算层测试：纯函数，无数据库、无网络。"""

import math

import pytest

from crossborder_ops.domain.advertising import (
    LEVEL_CRITICAL,
    LEVEL_INSUFFICIENT,
    LEVEL_OK,
    LEVEL_WARN,
    AdThresholds,
    acos,
    assess,
    compute_metrics,
    ctr,
    cvr,
    roas,
    safe_div,
)


# ---------- safe_div ----------

def test_safe_div_normal():
    assert safe_div(10, 4) == 2.5


def test_safe_div_zero_denominator_returns_none():
    assert safe_div(10, 0) is None


def test_safe_div_missing_returns_none():
    assert safe_div(None, 4) is None
    assert safe_div(10, None) is None


@pytest.mark.parametrize("bad", [-1, -0.5])
def test_safe_div_negative_raises(bad):
    with pytest.raises(ValueError):
        safe_div(bad, 1)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_safe_div_non_finite_raises(bad):
    with pytest.raises(ValueError):
        safe_div(bad, 1)


def test_safe_div_rejects_bool():
    with pytest.raises(ValueError):
        safe_div(True, 1)


# ---------- 四个指标 ----------

def test_acos_roas_ctr_cvr():
    assert acos(25.0, 100.0) == 0.25
    assert roas(100.0, 25.0) == 4.0
    assert ctr(50, 1000) == 0.05
    assert cvr(10, 50) == 0.2


def test_metrics_missing_denominator_is_none():
    assert acos(25.0, 0) is None
    assert roas(0.0, 25.0) == 0.0     # 销售额 0 是合法值，ROAS 就是 0
    assert ctr(50, 0) is None
    assert cvr(10, 0) is None
    assert cvr(10, None) is None


# ---------- compute_metrics ----------

def test_compute_metrics_full():
    m = compute_metrics(spend=25.0, clicks=50, orders=10, impressions=1000, sales=100.0)
    assert m.acos == 0.25
    assert m.roas == 4.0
    assert m.ctr == 0.05
    assert m.cvr == 0.2
    assert m.missing == ()


def test_compute_metrics_without_sales_and_impressions():
    m = compute_metrics(spend=25.0, clicks=50, orders=10)
    assert m.acos is None and m.roas is None
    assert m.ctr is None
    assert m.cvr == 0.2
    assert set(m.missing) == {"impressions", "sales"}


def test_compute_metrics_none_inputs_are_zero_and_marked_missing():
    m = compute_metrics(spend=None, clicks=None, orders=None)
    assert (m.spend, m.clicks, m.orders) == (0.0, 0, 0)
    assert {"spend", "clicks", "orders"} <= set(m.missing)


def test_compute_metrics_zero_clicks_no_crash():
    m = compute_metrics(spend=5.0, clicks=0, orders=0, impressions=0, sales=0.0)
    assert m.cvr is None and m.ctr is None
    assert m.acos is None          # sales=0 → 分母 0 → None，不是 inf
    assert m.roas == 0.0           # sales=0 / spend=5 → 0.0（分子是合法 0，不是缺失）


def test_compute_metrics_negative_raises():
    with pytest.raises(ValueError):
        compute_metrics(spend=-1.0, clicks=10, orders=1)
    with pytest.raises(ValueError):
        compute_metrics(spend=1.0, clicks=-5, orders=1)


def test_metrics_to_dict_is_json_friendly():
    d = compute_metrics(spend=1.2345678, clicks=10, orders=1, impressions=100, sales=10.0).to_dict()
    assert d["acos"] == 0.123456 or d["acos"] == round(0.12345678, 6)
    assert isinstance(d["missing"], list)


# ---------- assess ----------

def test_assess_insufficient_data_when_few_clicks():
    m = compute_metrics(spend=1.0, clicks=5, orders=0, impressions=100, sales=10.0)
    a = assess(m)
    assert a.level == LEVEL_INSUFFICIENT
    assert a.reasons


def test_assess_ok():
    m = compute_metrics(spend=10.0, clicks=100, orders=5, impressions=5000, sales=100.0)
    a = assess(m)
    assert a.level == LEVEL_OK
    assert a.reasons == ()


def test_assess_warn_on_high_acos():
    # 花 40 卖 100 → ACOS 40%：超过 warn(30%)，未到 critical(50%)
    m = compute_metrics(spend=40.0, clicks=200, orders=8, impressions=10000, sales=100.0)
    a = assess(m)
    assert a.level == LEVEL_WARN
    assert any("acos" in r for r in a.reasons)


def test_assess_critical_on_very_high_acos():
    # 花 60 卖 100 → ACOS 60% > critical
    m = compute_metrics(spend=60.0, clicks=200, orders=8, impressions=10000, sales=100.0)
    a = assess(m)
    assert a.level == LEVEL_CRITICAL
    assert any("acos" in r for r in a.reasons)


def test_assess_critical_on_low_roas():
    # ROAS = 1.5 <= roas_critical(2.0)
    m = compute_metrics(spend=100.0, clicks=200, orders=8, impressions=10000, sales=150.0)
    a = assess(m)
    assert a.level == LEVEL_CRITICAL
    assert any("roas" in r for r in a.reasons)


def test_assess_ignores_unavailable_metrics():
    """没有 sales/impressions 时，不能用"缺数据"推出 warn 或 critical。"""
    m = compute_metrics(spend=10.0, clicks=100, orders=5)
    a = assess(m)
    assert a.level == LEVEL_OK


def test_assess_custom_thresholds():
    # 只放宽 ACOS 两个阈值，ROAS 也要一起放宽，否则 ROAS=2.5 会先触发默认的 roas_warn=3.0
    m = compute_metrics(spend=40.0, clicks=200, orders=8, impressions=10000, sales=100.0)
    a = assess(m, AdThresholds(acos_warn=0.5, acos_critical=0.8,
                              roas_warn=1.0, roas_critical=0.5))
    assert a.level == LEVEL_OK


def test_assessment_to_dict():
    m = compute_metrics(spend=60.0, clicks=200, orders=8, impressions=10000, sales=100.0)
    d = assess(m).to_dict()
    assert d["level"] == LEVEL_CRITICAL
    assert isinstance(d["reasons"], list) and d["reasons"]
    assert d["metrics"]["acos"] == 0.6
