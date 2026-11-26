"""审批 API 请求模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=3, max_length=64)
    target_id: str = Field(min_length=1, max_length=64)
    after: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=4, max_length=120)
    reason: str | None = Field(default=None, max_length=2000)
    # 客户端只能提高风险等级，不能降低（服务端策略见 core/policy.py）
    risk_level: Literal["low", "medium", "high"] | None = None


class OperationSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)
