"""core/perf.py: 轻量性能监测工具。

提供：
  - timed(name)：上下文管理器 / 装饰器，记录命名操作的耗时。
  - PerfCollector：内存中的耗时统计（数量、总耗时、平均、最大、最小、最近一次）。
  - 导出 CSV 到文件。
  - 全局开关：由 config 控制，GUI 面板可切换。

用法：
    from core.perf import timed
    with timed("rss.fetch"):
        ...
"""
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque

from ..constants import DATA_DIR

from . import constants, profiler, runtime, threads, watchdog

# 共享可变对象（同一实例）：_lock / _records 经包内各切片引用同一对象
from .constants import (
    MAX_HEAD,
    PERF_CSV_PATH,
    PERF_ENABLED_KEY,
    PERF_LOG_DIR,
    _lock,
    _records,
    _start_time,
)
from .runtime import (
    _Timer,
    _traced_fns,
    enabled_funcs,
    export_csv,
    is_enabled,
    mark_webengine_alive,
    record,
    reset,
    set_enabled,
    stats,
    timed,
    trace,
    uptime_seconds,
    webengine_alive,
)
from .profiler import (
    profile_pause,
    profile_resume,
    profile_snapshot,
    profile_start,
    profile_stop,
)
from .threads import thread_snapshots
from .watchdog import (
    LAST_HEARTBEAT,
    WATCH_DISK_EVERY,
    WATCH_INTERVAL,
    WATCH_LOG,
    WATCH_LOG_KEEP_BYTES,
    WATCH_LOG_MAX_BYTES,
    _dump_history_to_disk,
    _format_stack,
    _last_disk_ts,
    _main_frame,
    _snapshot_history,
    _trim_watch_log,
    _watch_history,
    _watch_lock,
    _watch_stop,
    _watch_thread,
    _watchdog_loop,
    heartbeat,
    main_thread_signal,
    read_disk_signal,
    start_watchdog,
    stop_watchdog,
    watchdog_alive,
)

__all__ = [
    "mark_webengine_alive",
    "webengine_alive",
    "set_enabled",
    "is_enabled",
    "reset",
    "record",
    "stats",
    "export_csv",
    "uptime_seconds",
    "timed",
    "trace",
    "enabled_funcs",
    "profile_start",
    "profile_stop",
    "profile_pause",
    "profile_resume",
    "profile_snapshot",
    "thread_snapshots",
    "heartbeat",
    "main_thread_signal",
    "watchdog_alive",
    "read_disk_signal",
    "start_watchdog",
    "stop_watchdog",
]


def __getattr__(name):
    """活代理：被运行的 global 重绑的模块属性在此取切片当前值，
    避免 from-import 冻结拷贝导致开关语义回归。
    _cprofile/_profiler_enabled 归 profiler 切片；_enabled/_webengine_alive 归 runtime 切片。"""
    if name in ("_cprofile", "_profiler_enabled", "_profiler_paused"):
        return getattr(profiler, name)
    if name in ("_enabled", "_webengine_alive"):
        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")