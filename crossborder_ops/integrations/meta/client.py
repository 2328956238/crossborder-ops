"""Meta Graph API 客户端：分页、限流、退避、超时、异常分类、token 脱敏。

约束：
- access_token 只出现在请求参数里，日志/异常信息中一律脱敏；
- 429 优先用 Retry-After，其次指数退避 + jitter；
- 5xx / 网络错误可重试；401/403 不重试（直接抛 classified error）；
- 分页跟随 paging.next（绝对 URL）或 paging.cursors.after。
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ... import metrics
from ...config import get_settings
from .errors import (MetaAuthError, MetaConfigError, MetaError, MetaNetworkError,
                     MetaPermissionError, MetaRateLimited, MetaServerError)

logger = logging.getLogger(__name__)

RATE_LIMIT_CODES = {4, 17, 32, 613}
MAX_PAGES_HARD_LIMIT = 100


def redact(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    hidden = {"access_token", "appsecret_proof", "client_secret"}
    return {k: ("***" if k in hidden else v) for k, v in params.items()}


class MetaClient:
    """真实 Graph API 客户端（有 token 时才允许构造）。"""

    is_mock = False

    def __init__(self, access_token: str, *, graph_url: str | None = None,
                 api_version: str | None = None, timeout: float | None = None,
                 max_retries: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        settings = get_settings()
        if not access_token:
            raise MetaConfigError("缺少 access_token")
        self._token = access_token
        self._api_version = api_version or settings.meta_api_version
        self._base_url = f"{(graph_url or settings.meta_graph_url).rstrip('/')}/{self._api_version}"
        self._timeout = timeout or settings.meta_timeout_seconds
        self._max_retries = max_retries or settings.meta_max_retries
        self._transport = transport
        self.stats = {"requests": 0, "retries": 0, "throttled": 0, "pages": 0}

    # ---------------- 底层请求 ----------------
    async def _request(self, method: str, url: str, params: dict[str, Any] | None = None) -> dict:
        params = dict(params or {})
        params["access_token"] = self._token
        self._last_params = params      # 仅用于脱敏日志
        attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout,
                                             transport=self._transport) as http:
                    response = await http.request(method, url, params=params)
                self.stats["requests"] += 1
                metrics.META_REQUESTS.labels(method, str(response.status_code)).inc()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                metrics.META_REQUESTS.labels(method, "network_error").inc()
                raise MetaNetworkError(f"网络异常: {type(exc).__name__}") from exc

            if response.status_code == 200:
                return response.json()
            wait = self._classify(response)
            if attempt > self._max_retries:
                if response.status_code == 429:
                    raise MetaRateLimited("重试次数耗尽", status=response.status_code,
                                          retry_after=wait)
                raise MetaServerError("重试次数耗尽（平台 5xx）", status=response.status_code)
            self.stats["retries"] += 1
            metrics.META_REQUESTS.labels(method, "retry").inc()
            await asyncio.sleep(wait)

    def _classify(self, response: httpx.Response) -> float:
        """可重试错误返回等待秒数；不可重试错误直接抛分类异常。"""
        status = response.status_code
        detail = _safe_json(response)
        code = None
        err = detail.get("error") if isinstance(detail, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            message = str(err.get("message", ""))[:300]
        else:
            message = f"HTTP {status}"
        logger.warning("meta api error status=%s code=%s msg=%s params=%s",
                       status, code, message, redact(self._last_params))

        if status == 401 or code == 190:
            raise MetaAuthError(message or "token 失效", status=status, code=code)
        if status == 403 or code in (200, 294):
            raise MetaPermissionError(message or "权限不足", status=status, code=code)
        if status == 429 or code in RATE_LIMIT_CODES:
            metrics.META_THROTTLED.inc()
            return _retry_after(response)
        if 500 <= status < 600:
            return _retry_after(response)       # 平台故障：可重试
        raise MetaError(message or f"HTTP {status}", status=status, code=code)

    # ---------------- 分页 ----------------
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        self._last_params = params or {}
        return await self._request("GET", self._url(path), params)

    async def paginate(self, path: str, params: dict[str, Any] | None = None,
                       *, max_pages: int = MAX_PAGES_HARD_LIMIT) -> AsyncIterator[dict]:
        """逐个产出 data 里的条目，自动翻页。"""
        query = dict(params or {})
        self._last_params = query
        url = self._url(path)
        pages = 0
        while url and pages < max_pages:
            pages += 1
            payload = await self._request("GET", url, query)
            self.stats["pages"] += 1
            for item in payload.get("data", []) or []:
                yield item
            paging = payload.get("paging") or {}
            next_url = paging.get("next")
            if next_url:
                url = next_url                      # 绝对 URL，带 access_token
                query = {}
            else:
                cursor = (paging.get("cursors") or {}).get("after")
                if not cursor:
                    return
                url = self._url(path)
                query = {**params, "after": cursor}

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    # Meta 也会用 x-business-use-case-usage / 指数退避
    return min(30.0, (2 ** random.randint(0, 3)) * 0.5)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return None
