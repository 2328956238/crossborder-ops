"""Prometheus 指标：请求计数/耗时 + 业务计数器（后续阶段按需扩展）。"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .config import get_settings

REQUEST_COUNT = Counter(
    "crossborder_http_requests_total", "HTTP 请求数", ["method", "path", "status"])
REQUEST_LATENCY = Histogram(
    "crossborder_http_request_seconds", "HTTP 请求耗时", ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
SYNC_EVENTS = Counter(
    "crossborder_sync_events_total", "webhook 事件处理数", ["result"])


def install_metrics(app: FastAPI) -> None:
    if not get_settings().prometheus_enabled:
        return

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        elapsed = time.perf_counter() - started
        REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        return response


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
