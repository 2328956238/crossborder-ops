"""业务域计算测试：定价（Decimal）、库存（可售口径/补货）、Listing 内容校验。"""

from decimal import Decimal

import pytest

from crossborder_ops.domain import catalog
from crossborder_ops.domain import pricing as pd
from crossborder_ops.domain.inventory import InventoryParams, analyze_inventory


# ============================ 定价 ============================
ROW = {"unit_cost": 6.20, "commission_rate": 0.15, "shipping_fee": 2.80,
       "packaging_cost": 0.40, "target_margin": 0.25, "min_price": 15.00,
       "max_price": 27.00, "fee_source": "synthetic_assumption"}


def params(**over) -> pd.FeeParams:
    return pd.FeeParams.from_row({**ROW, **over})


def test_fixed_cost_breakeven_and_target_price():
    p = params()
    assert p.fixed_cost == Decimal("9.40")
    assert p.breakeven_price() == Decimal("11.06")      # 9.40 / 0.85
    assert p.target_price() == Decimal("15.67")         # 9.40 / 0.60


def test_profit_and_margin_are_decimal_with_two_dp():
    a = pd.analyze_price("19.99", "21.50", params())
    assert a.unit_profit == Decimal("7.59")             # 19.99*0.85-9.40
    assert str(a.margin_rate) == "0.3797"
    assert a.action == pd.ACTION_MAINTAIN


def test_increase_when_margin_below_target():
    # 成本抬高后利润率不足 → 建议涨价到 target_price
    a = pd.analyze_price("19.99", "21.50", params(unit_cost=12.00))
    assert a.action == pd.ACTION_INCREASE
    assert a.recommended_price == params(unit_cost=12.00).target_price()
    assert "低于目标" in " ".join(a.reasons)


def test_negative_profit_recommends_increase():
    # 成本 15.00 → 目标价 30.33 超过上限 27，系统会要求人工确认而不是硬涨价
    a = pd.analyze_price("19.99", "21.50", params(unit_cost=15.00))
    assert a.unit_profit < 0
    assert a.action == pd.ACTION_NEEDS_HUMAN
    assert a.recommended_price <= Decimal("27.00")


def test_below_min_price_needs_human():
    a = pd.analyze_price("3.00", "21.50", params())
    assert a.action == pd.ACTION_NEEDS_HUMAN
    assert a.warnings


def test_above_max_price_needs_human():
    a = pd.analyze_price("40.00", "21.50", params())
    assert a.action == pd.ACTION_NEEDS_HUMAN


def test_decrease_when_far_above_competitor_with_high_margin():
    a = pd.analyze_price("25.00", "18.00", params(min_price=15.00, max_price=27.00))
    assert a.action == pd.ACTION_DECREASE
    assert a.recommended_price >= Decimal("18.00")


def test_missing_fee_params_is_rejected():
    with pytest.raises(pd.PricingError) as exc:
        pd.FeeParams.from_row({**ROW, "unit_cost": None})
    assert exc.value.code == "missing_fee_params"


@pytest.mark.parametrize("bad", [{"commission_rate": 1.2}, {"target_margin": 0.9},
                                 {"min_price": 0}, {"max_price": 10.0}])
def test_invalid_fee_params(bad):
    with pytest.raises(pd.PricingError):
        params(**bad)


def test_price_must_be_positive():
    with pytest.raises(pd.PricingError):
        pd.analyze_price("0", "10", params())


def test_analysis_dict_has_currency_and_declaration():
    d = pd.analyze_price("19.99", "21.50", params()).to_dict()
    assert d["currency"] == "USD"
    assert "不代表 Amazon 真实收费" in d["cost"]["declaration"]
    assert d["prices"]["breakeven_price"].startswith("11.06")


# ============================ 库存 ============================
INV = {"sku": "SKU-A", "asin": "B0A", "on_hand": 100, "reserved": 20,
       "inbound": 50, "lead_time_days": 14, "target_cover_days": 30,
       "safety_stock": 20, "moq": 30}
P = InventoryParams.from_row(INV)


def test_available_excludes_inbound():
    a = analyze_inventory(INV, sold_units=70, window_days=7, params=P)
    assert a.available == 80              # 100-20，inbound 不计入
    assert a.days_of_cover == Decimal("8.00")
    assert a.level == "critical"          # 8 天 < 提前期 14 天
    assert a.recommended_qty >= 30


def test_replenishment_formula_and_moq():
    a = analyze_inventory(INV, sold_units=70, window_days=7, params=P)
    # daily 10 → ceil(10*(14+30)+20-80-50)=ceil(330)=330
    assert a.recommended_qty == 330
    assert "MOQ" in a.formula


def test_ok_and_warn_levels():
    ok = analyze_inventory({**INV, "on_hand": 500, "reserved": 0}, 70, 7, P)
    assert ok.level == "ok" and ok.recommended_qty == 0
    warn = analyze_inventory({**INV, "on_hand": 200, "reserved": 0}, 70, 7, P)
    assert warn.level == "warn"


def test_no_sales_is_not_safe():
    a = analyze_inventory(INV, sold_units=0, window_days=7, params=P)
    assert a.level in {"slow_moving", "no_sales"}
    assert a.days_of_cover is None
    assert a.recommended_qty == 0


def test_invalid_inventory_data():
    with pytest.raises(ValueError):
        analyze_inventory({**INV, "reserved": 200}, 0, 7, P)
    with pytest.raises(ValueError):
        analyze_inventory(INV, -1, 7, P)


# ============================ Listing 校验 ============================
GOOD = {"asin": "B0TEST0001", "title": "Silicone Phone Case for iPhone 15 Matte",
        "bullets": ["Slim 1.2mm profile pocket friendly"], "description": "x" * 40,
        "images": ["https://cdn.example.com/a/main.jpg"],
        "attributes": {"brand": "AcmeGear", "category": "Electronics"},
        "listing_status": "active"}


def test_valid_listing_passes():
    check = catalog.validate_listing(GOOD)
    assert check.passed and check.issues == ()
    assert check.rule_source == "demo_rules"


def test_bad_listing_reports_issues():
    check = catalog.validate_listing({"asin": "B0X", "title": "Case", "description": "",
                                      "bullets": [], "images": [],
                                      "attributes": {}, "listing_status": "bogus"})
    assert not check.passed
    fields = {i.field for i in check.issues}
    assert {"title", "description", "bullets", "images", "attributes.brand",
            "attributes.category", "listing_status"} <= fields


def test_bad_image_url_detected():
    check = catalog.validate_listing({**GOOD, "images": ["ftp://x/a.jpg"]})
    assert any(i.code == "url_format" for i in check.issues)


def test_diff_and_after_snapshot():
    after = catalog.build_after_snapshot(GOOD, {"title": "New Title For Case Product"})
    diff = catalog.diff_listing(GOOD, after)
    assert diff == [{"field": "title", "before": GOOD["title"],
                     "after": "New Title For Case Product"}]
    with pytest.raises(ValueError):
        catalog.build_after_snapshot(GOOD, {"sku": "HACK"})
