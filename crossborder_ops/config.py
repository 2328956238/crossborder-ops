"""应用配置：全部来自环境变量 / .env，禁止硬编码凭证。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 运行环境 ----
    app_env: str = "dev"
    app_name: str = "crossborder-ops"
    log_level: str = "INFO"

    # ---- 基础设施 ----
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/crossborder"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_tables: bool = True      # dev/test 用 create_all；生产用 alembic
    scheduler_enabled: bool = False
    prometheus_enabled: bool = True

    # ---- 认证：token -> {shop_id, actor, role} ----
    api_tokens: str = ""                 # JSON 字符串
    default_api_token: str = "dev-token"
    default_shop_id: str = "S1"
    default_actor: str = "dev"
    default_role: str = "admin"

    # ---- 平台 webhook ----
    webhook_secret: str = Field(default="", repr=False)   # 阶段 2 接入 HMAC 验签
    webhook_allowed_shops: str = ""                        # 逗号分隔的店铺白名单
    webhook_max_skew_seconds: int = 300                    # 时间戳允许偏差（防重放）

    # ---- Meta Marketing API ----
    meta_app_id: str = ""
    meta_app_secret: str = Field(default="", repr=False)
    meta_redirect_uri: str = "http://localhost:8000/api/v1/meta/oauth/callback"
    meta_graph_url: str = "https://graph.facebook.com"
    meta_api_version: str = "v21.0"
    meta_access_token: str = Field(default="", repr=False)
    meta_mock: bool = True               # 无真实凭证时必须走 Mock
    # token 加密 key（Fernet base64）；生产必填
    token_encryption_key: str = Field(default="", repr=False)
    meta_timeout_seconds: float = 15.0
    meta_max_retries: int = 3
    # 广告盾
    ad_shield_spend_drop_ratio: float = 0.3
    ad_shield_ctr_drop_ratio: float = 0.5
    ad_shield_cvr_drop_ratio: float = 0.5
    ad_shield_cpa_spike_ratio: float = 2.0
    # 告警通知：log / webhook
    notify_channel: str = "log"
    notify_webhook_url: str = ""

    # ---- 本地合成数据 ----
    local_data_dir: str = str(PROJECT_ROOT / "data" / "amazon")
    ads_seed_bids: str = '{"S1": {"kw1": 1.0, "kw2": 0.8}}'

    @property
    def token_map(self) -> dict[str, dict[str, str]]:
        if not self.api_tokens.strip():
            return {}
        try:
            data = json.loads(self.api_tokens)
        except json.JSONDecodeError as exc:  # 配置错误要显式失败，不要静默放行
            raise ValueError(f"API_TOKENS 不是合法 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("API_TOKENS 必须是 {token: {shop_id,...}} 结构")
        for token, entry in data.items():
            if not isinstance(entry, dict) or not entry.get("shop_id"):
                raise ValueError(f"API_TOKENS[{token}] 缺少 shop_id")
        return data

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
