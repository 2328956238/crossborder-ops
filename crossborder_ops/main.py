"""应用入口：create_app 工厂 + lifespan 生命周期。

阶段 1 只挂载：健康检查、webhook、operation 审批、只读数据接口（本地合成数据）。
阶段 2 起只读接口会被 PostgreSQL 仓储版替换。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .api.routers import (ad_shield, advertising, amazon, health, inventory, operations,
                          orders, products, reports, shops, webhooks)
from .config import get_settings
from .core.errors import AppError
from .db import dispose_engine, init_models
from .integrations.local.adapter import LocalDataAdapter, LocalDataError
from .metrics import install_metrics
from .workers.scheduler import Scheduler

logger = logging.getLogger("crossborder_ops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    if settings.auto_create_tables:
        # dev/test 便捷建表；生产必须走 alembic upgrade head
        await init_models()

    app.state.local_data = None
    try:
        app.state.local_data = LocalDataAdapter()
    except LocalDataError:
        logger.exception("本地合成数据初始化失败，只读接口将返回 503")

    scheduler = Scheduler(enabled=settings.scheduler_enabled)
    scheduler.start()
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.shutdown()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    install_metrics(app)

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(operations.router)
    app.include_router(amazon.router)
    # 阶段 2 业务模块
    app.include_router(shops.router)
    app.include_router(products.router)
    app.include_router(orders.router)
    app.include_router(inventory.router)
    app.include_router(advertising.router)
    app.include_router(ad_shield.router)
    app.include_router(reports.router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,
                            content={"ok": False, "error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        error = detail if isinstance(detail, dict) and "code" in detail else {
            "code": "http_error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": error})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"ok": False, "error": {
            "code": "validation_error",
            "message": "请求参数不合法；shop_id 不允许由客户端指定，只能由认证上下文注入",
            "details": jsonable_encoder(exc.errors()),
        }})

    return app


app = create_app()
