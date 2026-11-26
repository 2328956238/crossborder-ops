"""本地合成数据 Adapter 测试：过滤、关联、一致性、场景覆盖、错误处理。"""

import json
from pathlib import Path

import pytest

from crossborder_ops.config import get_settings
from crossborder_ops.integrations.local.adapter import LocalDataAdapter, LocalDataError

DATA = Path(get_settings().local_data_dir)


@pytest.fixture
def adapter():
    return LocalDataAdapter(DATA)


# ---------------------------------------------------------------------------
# 商品
# ---------------------------------------------------------------------------
def test_products_shop_isolation(adapter):
    s1 = adapter.products("S1")
    s2 = adapter.products("S2")
    assert len(s1) == 3 and len(s2) == 2
    assert {p["shop_id"] for p in s1} == {"S1"}
    assert not ({p["asin"] for p in s1} & {p["asin"] for p in s2})


def test_product_by_asin_and_sku(adapter):
    by_asin = adapter.product("S1", asin="B0TEST0002")
    by_sku = adapter.product("S1", sku="SKU-CHARGER-65W")
    assert by_asin["asin"] == by_sku["asin"] == "B0TEST0002"
    assert by_asin["price"] == 39.99 and by_asin["currency"] == "USD"


def test_product_missing_raises_not_found(adapter):
    with pytest.raises(LocalDataError) as exc:
        adapter.product("S1", asin="B0TEST9999")
    assert exc.value.code == "not_found"


def test_product_requires_identifier(adapter):
    with pytest.raises(LocalDataError) as exc:
        adapter.product("S1")
    assert exc.value.code == "invalid_arg"


def test_empty_asin_is_invalid(adapter):
    with pytest.raises(LocalDataError) as exc:
        adapter.products("S1", asin="")
    assert exc.value.code == "invalid_arg"


def test_unknown_shop_returns_empty(adapter):
    assert adapter.products("S9") == []
    assert adapter.orders("S9") == []


# ---------------------------------------------------------------------------
# 订单与一致性
# ---------------------------------------------------------------------------
def test_orders_link_to_products_and_amounts(adapter):
    products = {p["sku"]: p for p in adapter.products("S1")}
    orders = adapter.orders("S1", limit=100)
    assert orders, "应该有成单数据"
    for o in orders:
        p = products[o["sku"]]
        assert o["asin"] == p["asin"]
        assert abs(o["order_total"] - round(o["quantity"] * p["price"], 2)) < 1e-9


def test_order_filter_by_status_and_asins(adapter):
    canceled = adapter.orders("S1", status="Canceled", limit=100)
    assert canceled and all(o["status"] == "Canceled" for o in canceled)

    only_charger = adapter.orders("S1", asin="B0TEST0002", limit=100)
    assert only_charger and all(o["asin"] == "B0TEST0002" for o in only_charger)


def test_order_limit_and_invalid_limit(adapter):
    assert len(adapter.orders("S1", limit=3)) <= 3
    with pytest.raises(LocalDataError) as exc:
        adapter.orders("S1", limit=0)
    assert exc.value.code == "invalid_arg"


def test_order_stats_excludes_canceled_revenue(adapter):
    stats = adapter.order_stats("S1", days=7)
    assert stats["source"] == "synthetic"
    assert stats["order_count"] > 0 and stats["revenue"] > 0
    assert stats["by_status"].get("Canceled", 0) >= 1


# ---------------------------------------------------------------------------
# 库存与风险
# ---------------------------------------------------------------------------
def test_inventory_available_is_derived(adapter):
    rows = adapter.inventory("S1")
    assert len(rows) == 3
    for r in rows:
        assert r["available"] == r["on_hand"] - r["reserved"]
        assert 0 <= r["reserved"] <= r["on_hand"]


def test_inventory_risk_normal_has_no_critical(adapter):
    risks = adapter.inventory_risk("S1")
    levels = {r.sku: r.level for r in risks}
    assert levels  # 每个 SKU 都有评估
    assert "critical" not in levels.values(), levels


def test_low_inventory_scenario_turns_risk_critical():
    a = LocalDataAdapter(DATA, scenario="low_inventory")
    risks = {r.sku: r for r in a.inventory_risk("S1")}
    assert risks["SKU-CHARGER-65W"].level == "critical"
    assert risks["SKU-CHARGER-65W"].available == 4
    assert risks["SKU-CHARGER-65W"].days_of_cover is not None


def test_order_spike_scenario_lowers_days_of_cover():
    base = {r.sku: r for r in LocalDataAdapter(DATA).inventory_risk("S1")}
    spiked = {r.sku: r for r in LocalDataAdapter(DATA, scenario="order_spike").inventory_risk("S1")}
    assert spiked["SKU-CHARGER-65W"].days_of_cover < base["SKU-CHARGER-65W"].days_of_cover
    assert spiked["SKU-CHARGER-65W"].level == "critical"


# ---------------------------------------------------------------------------
# 价格与广告
# ---------------------------------------------------------------------------
def test_price_anomaly_detection():
    normal = LocalDataAdapter(DATA).price_anomalies("S1")
    assert normal == []                                   # 正常场景没有异常
    abnormal = LocalDataAdapter(DATA, scenario="price_anomaly").price_anomalies("S1")
    assert [p["asin"] for p in abnormal] == ["B0TEST0003"]
    assert abnormal[0]["anomaly"] == "too_low"


def test_ad_performance_uses_domain_metrics(adapter):
    perf = adapter.ad_performance("S1")
    assert perf["source"] == "synthetic"
    assert perf["metrics"]["acos"] == pytest.approx(201.4 / 468.85, rel=1e-4)
    assert perf["metrics"]["roas"] == pytest.approx(468.85 / 201.4, rel=1e-4)
    assert perf["assessment"]["level"] in {"warn", "critical"}


def test_ad_performance_single_asin_critical(adapter):
    perf = adapter.ad_performance("S1", asin="B0TEST0003")
    assert perf["metrics"]["acos"] > 1.0
    assert perf["assessment"]["level"] == "critical"


def test_advertising_drop_scenario_is_worse():
    base = LocalDataAdapter(DATA).ad_performance("S1", asin="B0TEST0002")["metrics"]["acos"]
    dropped = LocalDataAdapter(DATA, scenario="advertising_drop") \
        .ad_performance("S1", asin="B0TEST0002")["metrics"]["acos"]
    assert dropped > base


def test_ad_performance_not_found(adapter):
    with pytest.raises(LocalDataError) as exc:
        adapter.ad_performance("S2", asin="B0TEST0001")     # S1 的 ASIN，S2 没有广告
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------
def test_missing_data_dir_raises_file_missing(tmp_path):
    a = LocalDataAdapter(tmp_path)
    with pytest.raises(LocalDataError) as exc:
        a.products("S1")
    assert exc.value.code == "file_missing"


def test_unknown_scenario_raises():
    with pytest.raises(LocalDataError) as exc:
        LocalDataAdapter(DATA, scenario="does_not_exist")
    assert exc.value.code == "scenario_not_found"


def test_scenario_does_not_mutate_files():
    base_before = json.loads((DATA / "inventory.json").read_text(encoding="utf-8"))
    LocalDataAdapter(DATA, scenario="low_inventory").inventory("S1")
    base_after = json.loads((DATA / "inventory.json").read_text(encoding="utf-8"))
    assert base_before == base_after
