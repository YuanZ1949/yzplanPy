"""win_maintenance 模块：Windows 系统日志查看与过滤（只读）。"""
from .module import MODULE_INFO, Module
from .store import (
    read_event_log,
    get_log_stats,
    LEVEL_ERROR,
    LEVEL_WARNING,
    LEVEL_INFO,
)

__all__ = [
    "MODULE_INFO",
    "Module",
    "read_event_log",
    "get_log_stats",
    "LEVEL_ERROR",
    "LEVEL_WARNING",
    "LEVEL_INFO",
]