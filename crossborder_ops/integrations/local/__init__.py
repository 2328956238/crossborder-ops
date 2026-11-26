"""本地合成数据适配器（synthetic，仅用于演示与测试，不触达真实平台）。"""
from .adapter import LocalDataAdapter, LocalDataError, RiskItem

__all__ = ["LocalDataAdapter", "LocalDataError", "RiskItem"]
