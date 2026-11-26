"""Webhook 平台签名适配器：不同平台可各自实现，避免假设同一算法。

当前实现：HMAC-SHA256(timestamp + "." + raw_body)，常量时间比较。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code, "message": message})


def verify_signature(*, secret: str, timestamp: str | None, signature: str | None,
                     body: bytes, max_skew_seconds: int, required: bool) -> None:
    """验签失败抛 401；未配置 secret 且非必需时记录警告后放行（仅 dev）。"""
    if not secret:
        if required:
            raise HTTPException(status_code=500, detail={
                "code": "webhook_secret_not_configured",
                "message": "生产环境必须配置 WEBHOOK_SECRET"})
        logger.warning("WEBHOOK_SECRET 未配置：开发模式跳过验签（生产必须配置）")
        return
    if not timestamp or not signature:
        raise _unauthorized("webhook_signature_missing", "缺少 X-Timestamp / X-Signature")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise _unauthorized("webhook_timestamp_invalid", "时间戳格式不合法") from exc
    if abs(time.time() - ts) > max_skew_seconds:
        raise _unauthorized("webhook_timestamp_expired", "请求已过期（可能为重放）")

    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    provided = signature.strip()
    if provided.startswith("sha256="):
        provided = provided.split("=", 1)[1]
    if not hmac.compare_digest(expected, provided):
        raise _unauthorized("webhook_signature_invalid", "签名不匹配")
