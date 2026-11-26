"""Meta API 异常分类：不同错误必须能被区分，不能混成"账户风险"。"""
from __future__ import annotations


class MetaError(Exception):
    kind = "meta_error"
    retryable = False

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None):
        self.status = status
        self.code = code
        super().__init__(message)


class MetaConfigError(MetaError):
    """缺少 app id/secret/token 等配置。"""
    kind = "config"


class MetaAuthError(MetaError):
    """401 / OAuthException 190：token 失效或过期。"""
    kind = "auth"


class MetaPermissionError(MetaError):
    """403 / 权限不足：不等于封号。"""
    kind = "permission"


class MetaRateLimited(MetaError):
    """429 / error code 4/17/32：需要退避重试。"""
    kind = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, retry_after: float = 1.0, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class MetaServerError(MetaError):
    """5xx：平台故障，可重试。"""
    kind = "server"
    retryable = True


class MetaNetworkError(MetaError):
    """超时/连接中断：结果未知，写操作不得重试。"""
    kind = "network"


class MetaMockMisuse(MetaError):
    """缺少真实凭证却试图走真实 API。"""
    kind = "mock_misuse"
