"""win_maintenance 模块：Windows 系统日志查看与过滤（只读）。"""
from .module import MODULE_INFO, Module
from .store import (
    read_event_log,
    get_log_stats,
    aggregate_errors,
    LEVEL_ERROR,
    LEVEL_WARNING,
    LEVEL_INFO,
)
from .home import _make_home_widget
from .page import _make_page_widget

__all__ = [
    "MODULE_INFO",
    "Module",
    "read_event_log",
    "get_log_stats",
    "aggregate_errors",
    "LEVEL_ERROR",
    "LEVEL_WARNING",
    "LEVEL_INFO",
    "_make_home_widget",
    "_make_page_widget",
]