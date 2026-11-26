"""Meta 集成入口：按配置构建真实客户端或 Mock（绝不静默假装真实成功）。"""
from __future__ import annotations

from ...config import get_settings
from .client import MetaClient
from .errors import MetaConfigError
from .mock import MockMetaClient


def build_meta_client(access_token: str | None = None):
    settings = get_settings()
    token = access_token or settings.meta_access_token
    if settings.meta_mock:
        return MockMetaClient()
    if not token:
        raise MetaConfigError("META_MOCK=false 但未提供 access_token")
    return MetaClient(token)


def meta_status() -> dict:
    settings = get_settings()
    return {
        "mock": settings.meta_mock,
        "source": "mock" if settings.meta_mock else "meta",
        "has_app_id": bool(settings.meta_app_id),
        "has_app_secret": bool(settings.meta_app_secret),
        "graph_url": settings.meta_graph_url,
        "api_version": settings.meta_api_version,
        "note": ("未配置真实凭证，所有数据为 Mock" if settings.meta_mock
                 else "真实 Meta API 模式"),
    }


__all__ = ["build_meta_client", "meta_status", "MetaClient", "MockMetaClient"]
