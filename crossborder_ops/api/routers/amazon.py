"""Amazon 运营数据只读接口（本地合成数据）。

设计原则：
1. 只读：没有任何写接口，调价仍只能走审批链；
2. shop_id 只来自认证上下文，客户端不能指定；
3. 每个响应都带 `source: "synthetic"` 和声明，避免把本地数据误认为真实 Amazon 数据；
4. 不重复造错误结构，沿用 `{ok, data}` / `{ok, error{code,message}}`。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...integrations.local.adapter import LocalDataAdapter, LocalDataError
from ..deps import ShopContext as AuthContext, get_auth_context

logger = logging.getLogger("hub.api.amazon")

router = APIRouter(prefix="/api/v1/amazon", tags=["amazon-data"])


async def get_local_data(request: Request) -> LocalDataAdapter:
    data = getattr(request.app.state, "local_data", None)
    if data is None:
        logger.error("本地数据源未初始化")
        raise HTTPException(status_code=503, detail={
            "code": "data_unavailable",
            "message": "数据服务暂不可用，请稍后重试或联系管理员",
        })
    return data


def _raise_for(exc: LocalDataError) -> None:
    status = {"invalid_arg": 422, "not_found": 404, "scenario_not_found": 404}.get(exc.code, 503)
    if status == 503:
        logger.error("本地数据读取失败: %s: %s", exc.code, exc.message)
        raise HTTPException(status_code=503, detail={
            "code": "data_unavailable", "message": "数据服务暂不可用，请稍后重试或联系管理员"})
    raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


def _wrap(shop_id: str, data: LocalDataAdapter, **payload: Any) -> dict[str, Any]:
    return {"ok": True, "data": {
        "shop_id": shop_id,
        "source": "synthetic",
        "note": "本地合成业务数据，非真实卖家数据、非官方 Sandbox 返回、非实时库存",
        "scenario": data.scenario, **payload,
    }}


@router.get("/products")
async def list_products(
    asin: str | None = Query(default=None, min_length=1, max_length=20),
    sku: str | None = Query(default=None, min_length=1, max_length=64),
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    try:
        items = data.products(ctx.shop_id, asin=asin, sku=sku)
    except LocalDataError as exc:
        _raise_for(exc)
    if (asin or sku) and not items:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": f"商品不存在: asin={asin} sku={sku}"})
    return _wrap(ctx.shop_id, data, items=items, count=len(items))


@router.get("/orders")
async def list_orders(
    status: str | None = Query(default=None, max_length=32),
    asin: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=10, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    try:
        items = data.orders(ctx.shop_id, status=status, asin=asin, limit=limit)
        stats = data.order_stats(ctx.shop_id, days=7)
    except LocalDataError as exc:
        _raise_for(exc)
    return _wrap(ctx.shop_id, data, items=items, count=len(items), stats=stats)


@router.get("/inventory")
async def list_inventory(
    sku: str | None = Query(default=None, max_length=64),
    asin: str | None = Query(default=None, max_length=20),
    low_only: bool = Query(default=False),
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    try:
        items = data.inventory(ctx.shop_id, sku=sku, asin=asin, low_only=low_only)
        risk = [r.to_dict() for r in data.inventory_risk(ctx.shop_id)]
    except LocalDataError as exc:
        _raise_for(exc)
    if (sku or asin) and not items:
        raise HTTPException(status_code=404, detail={
            "code": "not_found", "message": f"库存记录不存在: sku={sku} asin={asin}"})
    return _wrap(ctx.shop_id, data, items=items, count=len(items), risk=risk)


@router.get("/advertising")
async def advertising_overview(
    asin: str | None = Query(default=None, max_length=20),
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    try:
        rows = data.advertising(ctx.shop_id, asin=asin)
        performance = data.ad_performance(ctx.shop_id, asin=asin) if rows else None
    except LocalDataError as exc:
        _raise_for(exc)
    return _wrap(ctx.shop_id, data, items=rows, count=len(rows), performance=performance)


@router.get("/summary")
async def ops_summary(
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    """综合运营只读汇总（商品数 / 7 天订单 / 库存风险 / 广告 / 价格异常）。"""
    try:
        risk = data.inventory_risk(ctx.shop_id)
        stats = data.order_stats(ctx.shop_id, days=7)
        perf = data.ad_performance(ctx.shop_id)
        anomalies = data.price_anomalies(ctx.shop_id)
        products = data.products(ctx.shop_id)
    except LocalDataError as exc:
        _raise_for(exc)
    return _wrap(
        ctx.shop_id, data,
        summary={
            "products": len(products),
            "orders_7d": stats["order_count"],
            "revenue_7d": stats["revenue"],
            "inventory_critical": sum(1 for r in risk if r.level == "critical"),
            "inventory_warn": sum(1 for r in risk if r.level == "warn"),
            "ad_level": perf["assessment"]["level"],
            "price_anomalies": len(anomalies),
        },
        inventory_risk=[r.to_dict() for r in risk],
        order_stats=stats,
        ad_performance=perf,
        price_anomalies=anomalies,
    )


@router.get("/pricing")
async def list_pricing(
    asin: str | None = Query(default=None, max_length=20),
    ctx: AuthContext = Depends(get_auth_context),
    data: LocalDataAdapter = Depends(get_local_data),
):
    """定价分析：成本/利润/保本价/目标价/竞品偏离（Decimal 计算，纯本地数据）。"""
    from ...domain import pricing as pricing_domain

    try:
        rows = data.prices(ctx.shop_id, asin=asin)
        if asin and not rows:
            raise LocalDataError("not_found", f"价格记录不存在: asin={asin}")
        items = []
        for row in rows:
            params = pricing_domain.FeeParams.from_row(row)
            analysis = pricing_domain.analyze_price(
                row["price"], row.get("competitor_price"), params)
            items.append({"asin": row["asin"], "is_buybox": row.get("is_buybox"),
                          "current_price": row["price"],
                          "competitor_price": row.get("competitor_price"),
                          "analysis": analysis.to_dict()})
    except LocalDataError as exc:
        _raise_for(exc)
    except pricing_domain.PricingError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    return _wrap(ctx.shop_id, data, items=items, count=len(items))
