"""统一错误类型：service 层抛 AppError，API 层只负责映射 HTTP 状态码。"""
from __future__ import annotations


class AppError(Exception):
    code: str = "app_error"
    status_code: int = 400

    def __init__(self, message: str = "", code: str | None = None):
        self.message = message or self.code
        super().__init__(self.message)
        if code:
            self.code = code


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ForbiddenShopError(AppError):
    code = "forbidden_shop"
    status_code = 403


class ValidationError(AppError):
    code = "invalid_arg"
    status_code = 422


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class DataUnavailableError(AppError):
    code = "data_unavailable"
    status_code = 503


class ApprovalError(AppError):
    """审批/执行状态机错误（沿用源仓库错误码，便于 API 映射）。"""

    _STATUS = {"not_found": 404, "forbidden_shop": 403, "invalid_arg": 422,
               "unknown_action": 422}

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code, code=code)
        self.status_code = self._STATUS.get(code, 400)
