"""core/perf: 计时核心（timed/record/stats/export）与 trace 包装。"""
import os
import time
from .constants import PERF_CSV_PATH, _enabled, _lock, _records, _start_time, _webengine_alive

def mark_webengine_alive(alive):
    """标记 QtWebEngine 预览是否为存活状态（rss_aggregator 调用）。"""
    global _webengine_alive
    _webengine_alive = bool(alive)


def webengine_alive():
    """返回当前是否有存活的 QtWebEngine 预览（供 GC 定时器查询）。"""
    return _webengine_alive


def set_enabled(value):
    global _enabled
    _enabled = bool(value)
    if not _enabled:
        with _lock:
            _records.clear()


def is_enabled():
    return _enabled


def reset():
    with _lock:
        _records.clear()


def record(name, duration):
    if not _enabled:
        return
    with _lock:
        _records[name].append((duration, time.time()))


def stats():
    """返回按名称聚合的统计列表。"""
    with _lock:
        out = []
        ordered = sorted(_records.keys())
        for name in ordered:
            dq = _records[name]
            if not dq:
                continue
            durations = [d for d, _ in dq]
            n = len(durations)
            total = sum(durations)
            avg = total / n
            out.append({
                "name": name,
                "count": n,
                "total_ms": round(total * 1000, 2),
                "avg_ms": round(avg * 1000, 2),
                "max_ms": round(max(durations) * 1000, 2),
                "min_ms": round(min(durations) * 1000, 2),
                "last_ms": round(durations[-1] * 1000, 2),
            })
        return out


def export_csv(path=None):
    """把统计导出为 CSV 文件，返回路径。"""
    path = path or PERF_CSV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = stats()
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.writer(f)
        writer.writerow(["name", "count", "total_ms", "avg_ms", "max_ms", "min_ms", "last_ms"])
        for r in rows:
            writer.writerow([r["name"], r["count"], r["total_ms"], r["avg_ms"],
                             r["max_ms"], r["min_ms"], r["last_ms"]])
    return path


def uptime_seconds():
    return time.time() - _start_time


class _Timer:
    def __init__(self, name):
        self.name = name
        self._t0 = None

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        dur = time.perf_counter() - self._t0
        record(self.name, dur)
        return False


def timed(name):
    """返回可作 with 使用 / 用作装饰器的计时器。"""
    return _Timer(name)


# ── 函数级监测 ────────────────────────────────────────────────────────

_traced_fns = {}        # func -> wrapper（避免重复包装）
_cprofile = None        # 系统级函数采样器状态
_profiler_enabled = False


def trace(max_depth=None):
    """装饰器 / 手动包装：自动统计单个函数的调用次数与耗时，按 模块.函数名 记录。

    用法:
        from core.perf import trace
        @trace()
        def my_func(...):
            ...
    """
    def deco(func):
        qualname = getattr(func, "__qualname__", func.__name__)
        mod = getattr(func, "__module__", "")
        label = f"{mod}.{qualname}" if mod else qualname
        if func in _traced_fns:
            return _traced_fns[func]

        import functools
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not _enabled:
                return func(*args, **kwargs)
            t0 = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                record(label, time.perf_counter() - t0)

        _traced_fns[func] = wrapper
        return wrapper
    return deco


def enabled_funcs():
    """返回已标记 trace 的函数标签列表。"""
    return sorted({f"{getattr(f,'__module__','')}.{getattr(f,'__qualname__',f.__name__)}"
                   for f in _traced_fns})
