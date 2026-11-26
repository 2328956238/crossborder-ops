"""Token 加密存储：Fernet 对称加密，明文 token 只存在于内存。

- 生产：必须配置 TOKEN_ENCRYPTION_KEY（Fernet key，base64 32 bytes）；
- 开发/测试：未配置时用固定 dev key 派生（会打一次警告），重启后旧密文仍可解。
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    pass


def _dev_key() -> str:
    digest = hashlib.sha256(b"crossborder-ops-dev-only-key").digest()
    return base64.urlsafe_b64encode(digest).decode()


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.token_encryption_key.strip()
    if not key:
        if settings.is_production:
            raise EncryptionError("生产环境必须配置 TOKEN_ENCRYPTION_KEY")
        logger.warning("未配置 TOKEN_ENCRYPTION_KEY，使用开发默认 key（仅限本地/测试）")
        key = _dev_key()
    try:
        return Fernet(key.encode())
    except Exception as exc:  # noqa: BLE001
        raise EncryptionError(f"TOKEN_ENCRYPTION_KEY 不合法: {exc}") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError("token 解密失败（key 不匹配或密文损坏）") from exc


def mask(token: str) -> str:
    """日志/响应里只允许出现掩码值。"""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}***{token[-4:]}"
