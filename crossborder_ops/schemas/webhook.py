"""webhook 请求体校验：shop_id 来自平台签名上下文（阶段 2 接验签），
字段严格校验，未知字段拒绝（防止上游悄悄改协议）。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: str = Field(min_length=1, max_length=64)
    event_id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    event_time: str = Field(min_length=10, max_length=40,
                            description="UTC ISO-8601，如 2026-01-10T12:00:00+00:00")
    order_id: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=32)

    def to_dict(self) -> dict:
        return self.model_dump()
