"""生成本地模拟业务数据（可重复执行，结果确定）。

声明：全部为合成数据（synthetic），不是真实卖家数据、不是官方 Sandbox 返回、不是实时库存。
运行：python tools/gen_local_data.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "amazon"
BASE_DAY = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)

PRODUCTS = [
    {"shop_id": "S1", "asin": "B0TEST0001", "sku": "SKU-CASE-001",
     "title": "Silicone Phone Case for iPhone 15 (Matte Black)", "brand": "AcmeGear",
     "category": "Electronics > Phone Accessories", "price": 19.99,
     "description": "Slim shockproof case with matte finish, raised bezel and precise cutouts.",
     "bullets": ["Slim 1.2mm profile, pocket friendly", "Shockproof corners with 2m drop protection",
                 "Raised bezel protects camera and screen", "Precise cutouts for buttons and ports",
                 "Matte anti-fingerprint coating"],
     "images": ["https://cdn.example.com/B0TEST0001/main.jpg",
                "https://cdn.example.com/B0TEST0001/back.jpg"],
     "attributes": {"brand": "AcmeGear", "color": "Matte Black", "material": "Silicone"},
     "listing_status": "active", "product_type": "PRODUCT"},
    {"shop_id": "S1", "asin": "B0TEST0002", "sku": "SKU-CHARGER-65W",
     "title": "65W USB-C GaN Fast Charger 2-Port Compact Travel", "brand": "AcmeGear",
     "category": "Electronics > Chargers", "price": 39.99,
     "description": "Dual-port GaN charger with PD 3.0, foldable plug and 2m cable included.",
     "bullets": ["65W total output, PD 3.0 fast charging", "GaN technology, 40% smaller",
                 "Two ports share power intelligently", "Foldable plug for travel",
                 "Includes 2m USB-C cable"],
     "images": ["https://cdn.example.com/B0TEST0002/main.jpg",
                "https://cdn.example.com/B0TEST0002/ports.jpg"],
     "attributes": {"brand": "AcmeGear", "color": "White", "material": "GaN"},
     "listing_status": "active", "product_type": "PRODUCT"},
    {"shop_id": "S1", "asin": "B0TEST0003", "sku": "SKU-PAD-15W",
     "title": "15W Wireless Charging Pad with USB-C Cable", "brand": "AcmeGear",
     "category": "Electronics > Chargers", "price": 24.50,
     "description": "Qi-certified 15W wireless charging pad with anti-slip surface.",
     "bullets": ["15W fast wireless charging", "Qi certified for iPhone and Android",
                 "Anti-slip silicone surface", "Includes 1m USB-C cable",
                 "Over-temperature protection"],
     "images": ["https://cdn.example.com/B0TEST0003/main.jpg"],
     "attributes": {"brand": "AcmeGear", "color": "Black", "material": "ABS"},
     "listing_status": "active", "product_type": "PRODUCT"},
    {"shop_id": "S2", "asin": "B0TEST0101", "sku": "SKU-HUB-7IN1",
     "title": "USB-C Hub 7-in-1 with HDMI 4K and 100W PD", "brand": "OtherBrand",
     "category": "Electronics > Hubs", "price": 29.99,
     "description": "7-in-1 USB-C hub: HDMI 4K, three USB 3.0 ports, SD, microSD and 100W PD.",
     "bullets": ["4K HDMI output", "Three USB 3.0 ports", "SD and microSD readers",
                 "100W power delivery pass-through", "Aluminum housing"],
     "images": ["https://cdn.example.com/B0TEST0101/main.jpg"],
     "attributes": {"brand": "OtherBrand", "color": "Silver", "material": "Aluminum"},
     "listing_status": "active", "product_type": "PRODUCT"},
    {"shop_id": "S2", "asin": "B0TEST0102", "sku": "SKU-CABLE-2M",
     "title": "USB-C to USB-C Cable 2m 100W Braided", "brand": "OtherBrand",
     "category": "Electronics > Cables", "price": 9.99,
     "description": "Braided USB-C cable supporting 100W charging and 480Mbps data.",
     "bullets": ["100W charging", "480Mbps data", "Braided nylon jacket",
                 "2 meter length", "Reversible connector"],
     "images": ["https://cdn.example.com/B0TEST0102/main.jpg"],
     "attributes": {"brand": "OtherBrand", "color": "Grey", "material": "Nylon"},
     "listing_status": "active", "product_type": "PRODUCT"},
]

SALES_PLAN = {("S1", "SKU-CASE-001"): 35, ("S1", "SKU-CHARGER-65W"): 28,
              ("S1", "SKU-PAD-15W"): 21, ("S2", "SKU-HUB-7IN1"): 14,
              ("S2", "SKU-CABLE-2M"): 7}

INVENTORY = [
    {"shop_id": "S1", "sku": "SKU-CASE-001", "asin": "B0TEST0001", "warehouse": "FBA-US-EAST",
     "on_hand": 120, "reserved": 8, "inbound": 60,
     "lead_time_days": 14, "target_cover_days": 30, "safety_stock": 20, "moq": 50},
    {"shop_id": "S1", "sku": "SKU-CHARGER-65W", "asin": "B0TEST0002", "warehouse": "FBA-US-EAST",
     "on_hand": 18, "reserved": 5, "inbound": 0,
     "lead_time_days": 21, "target_cover_days": 30, "safety_stock": 15, "moq": 30},
    {"shop_id": "S1", "sku": "SKU-PAD-15W", "asin": "B0TEST0003", "warehouse": "FBA-US-EAST",
     "on_hand": 40, "reserved": 4, "inbound": 0,
     "lead_time_days": 14, "target_cover_days": 30, "safety_stock": 10, "moq": 20},
    {"shop_id": "S2", "sku": "SKU-HUB-7IN1", "asin": "B0TEST0101", "warehouse": "FBA-US-WEST",
     "on_hand": 60, "reserved": 3, "inbound": 0,
     "lead_time_days": 18, "target_cover_days": 30, "safety_stock": 12, "moq": 25},
    {"shop_id": "S2", "sku": "SKU-CABLE-2M", "asin": "B0TEST0102", "warehouse": "FBA-US-WEST",
     "on_hand": 200, "reserved": 10, "inbound": 0,
     "lead_time_days": 12, "target_cover_days": 30, "safety_stock": 30, "moq": 100},
]

# 成本与费率是 synthetic 假设，不代表 Amazon 真实收费标准
PRICING = [
    {"shop_id": "S1", "asin": "B0TEST0001", "price": 19.99, "competitor_price": 21.50,
     "is_buybox": True, "unit_cost": 6.20, "commission_rate": 0.15,
     "shipping_fee": 2.80, "packaging_cost": 0.40, "target_margin": 0.25,
     "min_price": 15.00, "max_price": 27.00},
    {"shop_id": "S1", "asin": "B0TEST0002", "price": 39.99, "competitor_price": 37.99,
     "is_buybox": False, "unit_cost": 11.50, "commission_rate": 0.15,
     "shipping_fee": 3.20, "packaging_cost": 0.50, "target_margin": 0.25,
     "min_price": 32.00, "max_price": 45.00},
    {"shop_id": "S1", "asin": "B0TEST0003", "price": 24.50, "competitor_price": 24.99,
     "is_buybox": True, "unit_cost": 8.00, "commission_rate": 0.15,
     "shipping_fee": 3.00, "packaging_cost": 0.40, "target_margin": 0.30,
     "min_price": 20.00, "max_price": 32.00},
    {"shop_id": "S2", "asin": "B0TEST0101", "price": 29.99, "competitor_price": 31.00,
     "is_buybox": True, "unit_cost": 12.00, "commission_rate": 0.15,
     "shipping_fee": 3.50, "packaging_cost": 0.50, "target_margin": 0.25,
     "min_price": 25.00, "max_price": 38.00},
    {"shop_id": "S2", "asin": "B0TEST0102", "price": 9.99, "competitor_price": 10.50,
     "is_buybox": True, "unit_cost": 3.20, "commission_rate": 0.15,
     "shipping_fee": 1.80, "packaging_cost": 0.30, "target_margin": 0.30,
     "min_price": 8.00, "max_price": 14.00},
]

ADVERTISING = [
    ("S1", "B0TEST0001", "SP-CASE-AUTO", "phone case iphone 15", 4200, 210, 9, 84.00, 179.91),
    ("S1", "B0TEST0002", "SP-CHARGER-EXACT", "65w gan charger", 2600, 130, 6, 62.40, 239.94),
    ("S1", "B0TEST0003", "SP-PAD-BROAD", "wireless charger pad", 3100, 90, 2, 55.00, 49.00),
    ("S2", "B0TEST0101", "SP-HUB-AUTO", "usb c hub hdmi", 1500, 60, 3, 21.00, 89.97),
    ("S2", "B0TEST0102", "SP-CABLE-EXACT", "usb c cable 2m", 900, 40, 2, 9.00, 19.98),
]


def build_products() -> list[dict]:
    return [{**p, "currency": "USD", "status": p["listing_status"], "source": "synthetic"}
            for p in PRODUCTS]


def build_orders() -> list[dict]:
    price = {(p["shop_id"], p["sku"]): p["price"] for p in PRODUCTS}
    asin_of = {(p["shop_id"], p["sku"]): p["asin"] for p in PRODUCTS}
    orders, seq = [], 0
    statuses = ["Shipped", "Shipped", "Shipped", "Pending", "Canceled"]
    for (shop, sku), total_qty in SALES_PLAN.items():
        remaining, day_offset = total_qty, 6
        while remaining > 0:
            qty = min(3, remaining)
            remaining -= qty
            seq += 1
            orders.append({
                "shop_id": shop, "order_id": f"{shop}-{1000 + seq:04d}-{seq:02d}",
                "asin": asin_of[(shop, sku)], "sku": sku, "quantity": qty,
                "currency": "USD", "item_price": price[(shop, sku)],
                "order_total": round(qty * price[(shop, sku)], 2),
                "status": statuses[seq % len(statuses)],
                "purchase_date": (BASE_DAY - timedelta(days=day_offset,
                                                       minutes=(seq * 37) % 600)).isoformat(),
                "fulfillment": "FBA", "channel": "Amazon", "source": "synthetic"})
            day_offset = max(0, day_offset - 1)
    orders.sort(key=lambda o: o["purchase_date"], reverse=True)
    return orders


def build_inventory() -> list[dict]:
    return [{**i, "available": i["on_hand"] - i["reserved"], "currency": "USD",
             "updated_at": "2026-01-10T09:00:00+00:00", "source": "synthetic"}
            for i in INVENTORY]


def build_pricing() -> list[dict]:
    return [{**p, "currency": "USD", "updated_at": "2026-01-10T09:00:00+00:00",
             "source": "synthetic", "fee_source": "synthetic_assumption（非 Amazon 真实费率）"}
            for p in PRICING]


def build_advertising() -> list[dict]:
    return [{"shop_id": s, "asin": a, "campaign": c, "keyword": k, "impressions": imp,
             "clicks": cl, "orders": od, "spend": sp, "sales": sa, "period_days": 7,
             "currency": "USD", "end_date": "2026-01-10", "source": "synthetic"}
            for s, a, c, k, imp, cl, od, sp, sa in ADVERTISING]


def _pricing_override(asin: str, **over) -> dict:
    base = next(p for p in PRICING if p["shop_id"] == "S1" and p["asin"] == asin)
    return {**base, "currency": "USD", "updated_at": "2026-01-10T09:00:00+00:00",
            "source": "synthetic", "fee_source": "synthetic_assumption（非 Amazon 真实费率）", **over}


def build_scenarios() -> dict[str, dict]:
    low_inv = next(i for i in INVENTORY if i["sku"] == "SKU-CHARGER-65W")
    base_product = next(p for p in PRODUCTS if p["asin"] == "B0TEST0001")
    return {
        "normal": {"name": "normal", "description": "正常销售场景", "source": "synthetic",
                   "overrides": {}, "expected": {}},
        "low_inventory": {
            "name": "low_inventory", "description": "库存不足：充电器可售仅 4 件",
            "source": "synthetic",
            "overrides": {"inventory": [{**low_inv, "on_hand": 6, "reserved": 2,
                                        "available": 4, "inbound": 0}]},
            "expected": {}},
        "order_spike": {
            "name": "order_spike", "description": "订单突增：充电器最近 2 天新增 24 单",
            "source": "synthetic",
            "overrides": {"orders_append": [
                {"shop_id": "S1", "asin": "B0TEST0002", "sku": "SKU-CHARGER-65W",
                 "quantity": 2, "count": 12, "status": "Pending", "days_ago": 0}]},
            "expected": {}},
        "advertising_drop": {
            "name": "advertising_drop", "description": "广告花费上升但销售额下降",
            "source": "synthetic",
            "overrides": {"advertising": [
                {"shop_id": "S1", "asin": "B0TEST0002", "campaign": "SP-CHARGER-EXACT",
                 "keyword": "65w gan charger", "impressions": 2600, "clicks": 130,
                 "orders": 2, "spend": 95.00, "sales": 79.98, "period_days": 7,
                 "currency": "USD", "end_date": "2026-01-10", "source": "synthetic"}]},
            "expected": {}},
        "price_anomaly": {
            "name": "price_anomaly", "description": "价格异常：无线充 2.50 远低于竞品",
            "source": "synthetic",
            "overrides": {"pricing": [_pricing_override("B0TEST0003", price=2.50)]},
            "expected": {}},
        "cost_increase": {
            "name": "cost_increase", "description": "成本上涨：手机壳成本 6.20 → 15.00，利润转负",
            "source": "synthetic",
            "overrides": {"pricing": [_pricing_override("B0TEST0001", unit_cost=15.00)]},
            "expected": {}},
        "bad_listing": {
            "name": "bad_listing", "description": "Listing 质量问题：标题过短、无 bullet、无图片",
            "source": "synthetic",
            "overrides": {"products": [{**base_product, "title": "Case", "description": "",
                                        "bullets": [], "images": [],
                                        "listing_status": "suppressed",
                                        "status": "suppressed"}]},
            "expected": {}},
    }


def _meta(mapping: str) -> dict:
    return {"source": "synthetic", "data_kind": "本地模拟业务数据",
            "declaration": "非真实卖家数据、非官方 Sandbox 返回、非实时库存；仅用于演示与测试",
            "field_mapping": mapping, "currency": "USD", "timezone": "UTC",
            "reference_date": "2026-01-10"}


def write(name: str, payload) -> None:
    path = DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def validate(products, orders, inventory, pricing, advertising) -> None:
    asins = {(p["shop_id"], p["asin"]) for p in products}
    skus = {(p["shop_id"], p["sku"]) for p in products}
    price = {(p["shop_id"], p["sku"]): p["price"] for p in products}
    for o in orders:
        assert (o["shop_id"], o["asin"]) in asins and (o["shop_id"], o["sku"]) in skus
        assert abs(o["order_total"] - round(o["quantity"] * price[(o["shop_id"], o["sku"])], 2)) < 1e-9
    for i in inventory:
        assert i["on_hand"] >= 0 and 0 <= i["reserved"] <= i["on_hand"]
        assert i["available"] == i["on_hand"] - i["reserved"]
        assert i["lead_time_days"] > 0 and i["target_cover_days"] > 0 and i["moq"] > 0
    for p in pricing:
        assert (p["shop_id"], p["asin"]) in asins
        assert 0 < p["commission_rate"] < 1 and p["target_margin"] < 1 - p["commission_rate"]
        assert p["min_price"] <= p["price"] <= p["max_price"]
    for p in products:
        assert p["listing_status"] in {"active", "inactive", "suppressed"}
    print(f"validated: products={len(products)} orders={len(orders)} inventory={len(inventory)} "
          f"pricing={len(pricing)} advertising={len(advertising)}")


def main() -> None:
    products, orders = build_products(), build_orders()
    inventory, pricing, advertising = build_inventory(), build_pricing(), build_advertising()
    validate(products, orders, inventory, pricing, advertising)
    write("products.json", {"meta": _meta("Catalog/Listings 简化视图"), "items": products})
    write("orders.json", {"meta": _meta("Orders API 扁平化视图"), "items": orders})
    write("inventory.json", {"meta": _meta("FBA Inventory + 补货参数"), "items": inventory})
    write("pricing.json", {"meta": _meta("Product Pricing + 成本/费率（synthetic 假设）"), "items": pricing})
    write("advertising.json", {"meta": _meta("广告报表聚合"), "items": advertising})
    for name, payload in build_scenarios().items():
        write(f"scenarios/{name}.json", payload)


if __name__ == "__main__":
    main()
