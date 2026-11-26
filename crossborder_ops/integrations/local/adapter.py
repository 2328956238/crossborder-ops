"""LocalDataAdapter：读取本地合成业务数据（商品 / 订单 / 库存 / 价格 / 广告）。

定位：
- 这是 **synthetic（合成）数据源**，用于演示与测试，**不是** Amazon 真实数据，
  也不是 SP-API Sandbox 返回（Sandbox 示例单独放在 data/amazon/fixtures/spapi/）；
- 只读：本模块不提供任何写方法，不需要审批；
- 数据加载与过滤逻辑全部在这里，**不允许写进 LangGraph 节点**。

错误约定（LocalDataError.code）：
- file_missing      数据文件不存在
- invalid_arg       参数非法（如 limit<1、days<1）
- not_found         查询的商品/订单/价格不存在
- scenario_not_found 场景文件不存在
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ...config import get_settings
from ...domain.advertising import AdAssessment, AdThresholds, assess, compute_metrics

DATA_SOURCE = "synthetic"
DEFAULT_DAY = "2026-01-10"


class LocalDataError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class RiskItem:
    sku: str
    asin: str
    available: int
    daily_sales: float
    days_of_cover: float | None
    level: str          # critical / warn / ok
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku, "asin": self.asin, "available": self.available,
            "daily_sales": round(self.daily_sales, 2),
            "days_of_cover": None if self.days_of_cover is None else round(self.days_of_cover, 2),
            "level": self.level, "reason": self.reason,
        }


class LocalDataAdapter:
    """本地合成数据读取器，支持场景覆盖（scenario）但不修改磁盘文件。"""

    def __init__(self, root: str | Path | None = None, scenario: str | None = None):
        self.root = Path(root) if root else Path(get_settings().local_data_dir)
        self.scenario = scenario
        self._overrides: dict[str, list[dict]] = {}
        # 写操作的本地 Mock 覆盖层：executed Operation 会写入这里，不修改磁盘 fixture
        self._overlay: dict[str, dict[str, dict]] = {"products": {}, "pricing": {}}
        if scenario:
            self._overrides = self._load_scenario(scenario)

    # ------------------------------------------------------------------
    # 内部：加载
    # ------------------------------------------------------------------
    def _read(self, name: str) -> list[dict]:
        path = self.root / f"{name}.json"
        if not path.exists():
            raise LocalDataError("file_missing", f"数据文件不存在: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LocalDataError("file_missing", f"数据文件损坏: {path}: {exc}") from exc
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise LocalDataError("file_missing", f"数据文件格式不对（缺 items 数组）: {path}")
        return [dict(x) for x in items]

    def _load_scenario(self, name: str) -> dict[str, list[dict]]:
        path = self.root / "scenarios" / f"{name}.json"
        if not path.exists():
            raise LocalDataError("scenario_not_found", f"场景不存在: {name}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        overrides = payload.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise LocalDataError("file_missing", f"场景格式不对: {path}")
        return overrides

    def _rows(self, name: str, key_field: str) -> list[dict]:
        rows = self._read(name)
        overrides = self._overrides.get(name) or []
        if overrides:
            by_key = {o.get(key_field): o for o in overrides if isinstance(o, dict)}
            merged: list[dict] = []
            for row in rows:
                override = by_key.pop(row.get(key_field), None)
                merged.append({**row, **override} if override else row)
            merged.extend(by_key.values())
            rows = merged
        overlay = self._overlay.get(name) or {}
        if overlay:
            rows = [{**row, **overlay[row[key_field]]} if row.get(key_field) in overlay else row
                    for row in rows]
        return rows

    def _orders(self) -> list[dict]:
        rows = self._rows("orders", "order_id")
        # 场景可以追加订单（order_spike）
        for spec in self._overrides.get("orders_append", []):
            count = int(spec.get("count", 0))
            qty = int(spec.get("quantity", 1))
            days_ago = int(spec.get("days_ago", 0))
            base = datetime.fromisoformat(f"{DEFAULT_DAY}T12:00:00+00:00") - timedelta(days=days_ago)
            for i in range(count):
                rows.append({
                    "shop_id": spec["shop_id"], "asin": spec["asin"], "sku": spec["sku"],
                    "order_id": f"{spec['shop_id']}-SPIKE-{i:03d}",
                    "quantity": qty, "currency": "USD",
                    "order_total": round(qty * 39.99, 2),
                    "status": spec.get("status", "Pending"),
                    "purchase_date": (base - timedelta(minutes=i * 7)).isoformat(),
                    "fulfillment": "FBA", "channel": "Amazon", "source": "synthetic",
                })
        return rows

    # ------------------------------------------------------------------
    # 商品
    # ------------------------------------------------------------------
    def products(self, shop_id: str, *, asin: str | None = None,
                 sku: str | None = None) -> list[dict]:
        if asin is not None and not asin.strip():
            raise LocalDataError("invalid_arg", "asin 不能为空字符串")
        if sku is not None and not sku.strip():
            raise LocalDataError("invalid_arg", "sku 不能为空字符串")
        out = [p for p in self._rows("products", "asin")
               if p["shop_id"] == shop_id
               and (asin is None or p["asin"] == asin)
               and (sku is None or p["sku"] == sku)]
        return out

    def product(self, shop_id: str, *, asin: str | None = None,
                sku: str | None = None) -> dict:
        if asin is None and sku is None:
            raise LocalDataError("invalid_arg", "必须提供 asin 或 sku")
        found = self.products(shop_id, asin=asin, sku=sku)
        if not found:
            raise LocalDataError("not_found", f"商品不存在: shop={shop_id} asin={asin} sku={sku}")
        return found[0]

    def listing_snapshot(self, shop_id: str, asin: str) -> dict:
        """可编辑字段快照：供 Operation 的 before_snapshot 使用。"""
        p = self.product(shop_id, asin=asin)
        from ..domain.catalog import EDITABLE_FIELDS
        return {k: p.get(k) for k in EDITABLE_FIELDS}

    def apply_listing(self, shop_id: str, asin: str, after: dict) -> dict:
        """由 Operation 执行器调用：写入本地 Mock 覆盖层（不改磁盘 fixture）。"""
        self.product(shop_id, asin=asin)          # 不存在则先抛 not_found
        self._overlay["products"][asin] = dict(after)
        return self.product(shop_id, asin=asin)

    def apply_price(self, shop_id: str, asin: str, price: float) -> dict:
        row = self.pricing_row(shop_id, asin)
        self._overlay["pricing"][asin] = {**row, "price": float(price),
                                          "updated_at": "2026-01-10T12:00:00+00:00"}
        return self.pricing_row(shop_id, asin)

    # ------------------------------------------------------------------
    # 订单
    # ------------------------------------------------------------------
    def orders(self, shop_id: str, *, status: str | None = None,
               asin: str | None = None, sku: str | None = None,
               since: str | None = None, limit: int = 20, offset: int = 0) -> list[dict]:
        if limit < 1 or limit > 200:
            raise LocalDataError("invalid_arg", "limit 必须在 1..200")
        if offset < 0:
            raise LocalDataError("invalid_arg", "offset 不能为负")
        rows = [o for o in self._orders() if o["shop_id"] == shop_id]
        if status:
            rows = [o for o in rows if str(o.get("status", "")).lower() == status.lower()]
        if asin:
            rows = [o for o in rows if o.get("asin") == asin]
        if sku:
            rows = [o for o in rows if o.get("sku") == sku]
        if since:
            rows = [o for o in rows if o.get("purchase_date", "") >= since]
        rows.sort(key=lambda o: o.get("purchase_date", ""), reverse=True)
        return rows[offset:offset + limit]

    def orders_page(self, shop_id: str, *, limit: int = 20, offset: int = 0,
                    **filters) -> dict:
        """游标式分页：返回 items + next_offset（没有更多则为 None）。"""
        items = self.orders(shop_id, limit=limit, offset=offset, **filters)
        next_offset = offset + limit if len(items) == limit else None
        return {"items": items, "offset": offset, "limit": limit,
                "next_offset": next_offset, "source": DATA_SOURCE}

    def order(self, shop_id: str, order_id: str) -> dict:
        if not (order_id or "").strip():
            raise LocalDataError("invalid_arg", "order_id 不能为空")
        for o in self._orders():
            if o["shop_id"] == shop_id and o["order_id"] == order_id:
                return o
        raise LocalDataError("not_found", f"订单不存在: {order_id}")

    def order_stats(self, shop_id: str, *, days: int = 7) -> dict:
        if days < 1 or days > 90:
            raise LocalDataError("invalid_arg", "days 必须在 1..90")
        cutoff = (datetime.fromisoformat(f"{DEFAULT_DAY}T00:00:00+00:00")
                  - timedelta(days=days)).isoformat()
        rows = [o for o in self.orders(shop_id, since=cutoff, limit=200)]
        by_status: dict[str, int] = {}
        revenue = 0.0
        units = 0
        for o in rows:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
            if o["status"] != "Canceled":
                revenue += float(o.get("order_total", 0))
                units += int(o.get("quantity", 0))
        return {
            "days": days, "order_count": len(rows), "by_status": by_status,
            "units": units, "revenue": round(revenue, 2), "currency": "USD",
            "source": DATA_SOURCE,
        }

    # ------------------------------------------------------------------
    # 库存
    # ------------------------------------------------------------------
    def inventory(self, shop_id: str, *, sku: str | None = None,
                  asin: str | None = None, low_only: bool = False,
                  low_threshold: int = 10) -> list[dict]:
        if low_threshold < 0:
            raise LocalDataError("invalid_arg", "low_threshold 不能为负")
        rows = [i for i in self._rows("inventory", "sku")
                if i["shop_id"] == shop_id
                and (sku is None or i["sku"] == sku)
                and (asin is None or i["asin"] == asin)]
        for row in rows:
            row["available"] = int(row.get("on_hand", 0)) - int(row.get("reserved", 0))
            if row["available"] < 0:
                raise LocalDataError("invalid_arg", f"库存出现无解释的负数: {row['sku']}")
        if low_only:
            rows = [r for r in rows if r["available"] <= low_threshold]
        return rows

    def inventory_risk(self, shop_id: str, *, days: int = 7,
                       warn_days: float = 7.0, critical_days: float = 3.0) -> list[RiskItem]:
        """按近 N 天日均销量估算可售天数；critical < critical_days <= warn < warn_days。"""
        if days < 1 or days > 90:
            raise LocalDataError("invalid_arg", "days 必须在 1..90")
        cutoff = (datetime.fromisoformat(f"{DEFAULT_DAY}T00:00:00+00:00")
                  - timedelta(days=days)).isoformat()
        orders = [o for o in self._orders()
                  if o["shop_id"] == shop_id and o["status"] != "Canceled"
                  and o.get("purchase_date", "") >= cutoff]
        sold: dict[str, int] = {}
        for o in orders:
            sold[o["sku"]] = sold.get(o["sku"], 0) + int(o.get("quantity", 0))

        items: list[RiskItem] = []
        for inv in self.inventory(shop_id):
            qty = sold.get(inv["sku"], 0)
            daily = qty / days
            cover = (inv["available"] / daily) if daily > 0 else None
            if cover is None:
                level, reason = "ok", "近期无销量，无法估算覆盖天数"
            elif cover < critical_days:
                level, reason = "critical", f"可售仅够 {cover:.1f} 天（< {critical_days} 天）"
            elif cover < warn_days:
                level, reason = "warn", f"可售可支撑 {cover:.1f} 天（< {warn_days} 天）"
            else:
                level, reason = "ok", f"可售可支撑 {cover:.1f} 天"
            items.append(RiskItem(sku=inv["sku"], asin=inv["asin"], available=inv["available"],
                                  daily_sales=daily, days_of_cover=cover,
                                  level=level, reason=reason))
        items.sort(key=lambda r: (r.days_of_cover if r.days_of_cover is not None else 999))
        return items

    # ------------------------------------------------------------------
    # 价格
    # ------------------------------------------------------------------
    def prices(self, shop_id: str, *, asin: str | None = None) -> list[dict]:
        return [p for p in self._rows("pricing", "asin")
                if p["shop_id"] == shop_id and (asin is None or p["asin"] == asin)]

    def pricing_row(self, shop_id: str, asin: str) -> dict:
        rows = self.prices(shop_id, asin=asin)
        if not rows:
            raise LocalDataError("not_found", f"价格记录不存在: asin={asin}")
        return rows[0]

    def inventory_analysis(self, shop_id: str, *, days: int = 7,
                           sku: str | None = None, asin: str | None = None,
                           level: str | None = None) -> list[dict]:
        """基于 domain/inventory 的完整分析（可售口径 + 覆盖天数 + 补货建议）。"""
        from ..domain.inventory import InventoryParams, analyze_inventory

        if days < 1 or days > 90:
            raise LocalDataError("invalid_arg", "days 必须在 1..90")
        cutoff = (datetime.fromisoformat(f"{DEFAULT_DAY}T00:00:00+00:00")
                  - timedelta(days=days)).isoformat()
        sold: dict[str, int] = {}
        for o in self._orders():
            if o["shop_id"] == shop_id and o["status"] != "Canceled" \
                    and o.get("purchase_date", "") >= cutoff:
                sold[o["sku"]] = sold.get(o["sku"], 0) + int(o.get("quantity", 0))

        out: list[dict] = []
        for row in self.inventory(shop_id, sku=sku, asin=asin):
            params = InventoryParams.from_row(row)
            analysis = analyze_inventory(row, sold.get(row["sku"], 0), days, params)
            item = analysis.to_dict()
            item.update({"warehouse": row.get("warehouse"),
                         "params": {"lead_time_days": params.lead_time_days,
                                    "target_cover_days": params.target_cover_days,
                                    "safety_stock": params.safety_stock, "moq": params.moq}})
            if level is None or item["level"] == level:
                out.append(item)
        return out

    def price_anomalies(self, shop_id: str, *, deviation: float = 0.5) -> list[dict]:
        """价格与竞品偏离超过 deviation（默认 50%）视为异常。"""
        if not 0 < deviation < 1:
            raise LocalDataError("invalid_arg", "deviation 必须在 (0,1)")
        out = []
        for p in self.prices(shop_id):
            comp = p.get("competitor_price")
            if not comp:
                continue
            diff = (p["price"] - comp) / comp
            if abs(diff) > deviation:
                out.append({**p, "deviation": round(diff, 4),
                            "anomaly": "too_low" if diff < 0 else "too_high",
                            "source": DATA_SOURCE})
        return out

    # ------------------------------------------------------------------
    # 广告
    # ------------------------------------------------------------------
    def advertising(self, shop_id: str, *, asin: str | None = None) -> list[dict]:
        return [a for a in self._rows("advertising", "asin")
                if a["shop_id"] == shop_id and (asin is None or a["asin"] == asin)]

    def ad_performance(self, shop_id: str, *, asin: str | None = None,
                       thresholds: AdThresholds | None = None) -> dict:
        """把广告行聚合成整体指标，并复用 domain 的 ACOS/ROAS/CTR/CVR 与阈值判断。"""
        rows = self.advertising(shop_id, asin=asin)
        if not rows:
            raise LocalDataError("not_found", f"没有广告数据: shop={shop_id} asin={asin}")
        spend = round(sum(float(r["spend"]) for r in rows), 2)
        sales = round(sum(float(r["sales"]) for r in rows), 2)
        clicks = sum(int(r["clicks"]) for r in rows)
        impressions = sum(int(r["impressions"]) for r in rows)
        orders = sum(int(r["orders"]) for r in rows)
        metrics = compute_metrics(spend=spend, clicks=clicks, orders=orders,
                                  impressions=impressions, sales=sales)
        assessment: AdAssessment = assess(metrics, thresholds)
        return {
            "shop_id": shop_id, "asin": asin, "period_days": max(int(r.get("period_days", 7)) for r in rows),
            "totals": {"spend": spend, "sales": sales, "clicks": clicks,
                       "impressions": impressions, "orders": orders},
            "metrics": metrics.to_dict(),
            "assessment": {"level": assessment.level, "reasons": list(assessment.reasons)},
            "currency": "USD", "source": DATA_SOURCE,
        }

    # ------------------------------------------------------------------
    # 场景
    # ------------------------------------------------------------------
    def scenario_meta(self) -> dict:
        if not self.scenario:
            return {"scenario": None, "source": DATA_SOURCE}
        path = self.root / "scenarios" / f"{self.scenario}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            "scenario": self.scenario,
            "description": payload.get("description", ""),
            "source": DATA_SOURCE,
        }
