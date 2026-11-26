"""健康检查 / 就绪 / Prometheus 指标。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ... import __version__
from ...config import get_settings
from ...db import get_session
from ...metrics import render_metrics

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"ok": True, "version": __version__, "env": get_settings().app_env}


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)):
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 就绪检查不抛异常，返回状态
        checks["database"] = f"error:{type(exc).__name__}"
    overall = all(v == "ok" for v in checks.values())
    return {"ok": overall, "checks": checks}


@router.get("/metrics")
async def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
