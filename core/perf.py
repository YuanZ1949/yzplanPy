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

from .constants import DATA_DIR

PERF_LOG_DIR = os.path.join(DATA_DIR, "logs")
PERF_CSV_PATH = os.path.join(PERF_LOG_DIR, "perf_stats.csv")
PERF_ENABLED_KEY = "performance.enabled"

_lock = threading.Lock()
_records = defaultdict(lambda: deque(maxlen=1000))  # name -> deque[(duration, time)]
_enabled = True
_start_time = time.time()

MAX_HEAD = 500

# WebEngine 预览常驻标记：只要有 QtWebEngine 预览对象存活，就禁止任何位置
# 强制的 gc.collect()（回收其 shiboken 包装会在渲染子进程仍引用时导致
# 0x8001010d / Aborted 崩溃）。由 rss_aggregator 在创建/销毁预览时切换，
# 由主线程定期 GC 定时器在此处查询后才决定是否收集。
_webengine_alive = False


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


# ── 系统级函数采样器（cProfile 热点）──────────────────────────────────

def profile_start():
    """启用基于 sys.setprofile 的函数采样器，统计各函数被调次数与自用时间。"""
    global _cprofile, _profiler_enabled
    if _profiler_enabled:
        return
    # 采样器使用独立锁，绝不能与 stats()/record() 共用的 _lock 混用，
    # 否则采样钩子在 stats() 迭代期间触发时会死锁（_lock 不可重入）。
    hook_lock = threading.Lock()
    stats = {"func": {}, "call": 0}

    def _hook(frame, event, arg):
        # 注意：务必返回 None。sys.setprofile 的返回值为非 None 时，
        # 会让该函数自身的内部调用也触发本钩子，从而无限递归 + 死锁。
        if event not in ("call", "return"):
            return None
        code = frame.f_code
        key = f"{code.co_filename}:{code.co_firstlineno} {code.co_name}"
        with hook_lock:
            ent = stats["func"].setdefault(key, {"calls": 0, "self_s": 0.0, "t0": None})
            if event == "call":
                ent["calls"] += 1
                ent["t0"] = time.perf_counter()
            elif event == "return" and ent.get("t0") is not None:
                ent["self_s"] += time.perf_counter() - ent["t0"]
                ent["t0"] = None
        return None

    _cprofile = {"stats": stats, "hook": _hook, "lock": hook_lock}
    sys.setprofile(_hook)
    _profiler_enabled = True


def profile_stop():
    """停止函数采样器。"""
    global _cprofile, _profiler_enabled
    if not _profiler_enabled:
        return
    sys.setprofile(None)
    _profiler_enabled = False


def profile_snapshot():
    """返回采样器当前统计（调用次数 + 自用秒数）。"""
    global _cprofile
    if not _cprofile or not _profiler_enabled:
        return []
    stats = _cprofile["stats"]
    hook_lock = _cprofile["lock"]
    # 必须使用采样器的独立锁（与 _lock 不同），否则迭代期间
    # 采样钩子在其它线程并发写 stats["func"] 会触发
    # "dictionary changed size during iteration"。
    with hook_lock:
        rows = []
        for key, ent in stats["func"].items():
            rows.append({
                "name": key,
                "count": ent["calls"],
                "self_s": round(ent["self_s"], 4),
                "avg_s": round(ent["self_s"] / ent["calls"], 6) if ent["calls"] else 0,
            })
    rows.sort(key=lambda r: r["self_s"], reverse=True)
    return rows[:200]


# ── 线程实时栈快照 ────────────────────────────────────────────────────

def thread_snapshots():
    """抓取各线程当前正在执行的函数栈（用于定位卡顿/死锁现场）。

    说明：sys._current_frames() 只能看到「有 Python PyThreadState 的线程」——
    Qt 内部线程池、C 扩展自建的原生线程不可见。这里用 psutil 枚举进程全部
    OS 线程（含原生），再与 Python 帧交叉比对，标注缺失类别。
    """
    import sys as _sys
    import threading as _threading
    frames = _sys._current_frames()
    python_tids = set(frames.keys())
    main_tid = _threading.main_thread().ident

    all_tids = {}
    try:
        import psutil
        for t in psutil.Process().threads():
            all_tids[t.id] = t
    except Exception:
        all_tids = {}

    result = []
    # 先列出有 Python 帧的线程（保持原有顺序）
    for tid in sorted(python_tids):
        frame = frames[tid]
        stack = []
        f = frame
        while f is not None:
            name = f.f_code.co_name
            filename = f.f_code.co_filename
            lineno = f.f_lineno
            stack.append(f"{name} ({filename}:{lineno})")
            f = f.f_back
            if len(stack) >= 20:
                break
        entry = {"thread_id": tid, "stack": list(reversed(stack))}
        if tid == main_tid:
            entry["main"] = True
        result.append(entry)

    # 再列出现有 deps/psutil 可见、但没有任何 Python 帧的原生线程
    for tid in sorted(all_tids):
        if tid in python_tids:
            continue
        pt = all_tids[tid]
        extra = []
        try:
            if pt.user_time or pt.system_time:
                extra.append(f"cpu {pt.user_time:.2f}s/{pt.system_time:.2f}s")
        except Exception:
            pass
        result.append({
            "thread_id": tid,
            "stack": [],
            "native": True,
            "note": "原生线程（无 Python 帧）" + (f"  {extra[0]}" if extra else ""),
        })
    return result


# ── 卡死排查：常驻守护线程 + 主线程飞行记录 ─────────────────────────

WATCH_LOG = os.path.join(PERF_LOG_DIR, "perf_threads.log")
WATCH_INTERVAL = 0.5      # 抓主线程栈的间隔（秒）
WATCH_DISK_EVERY = 5.0     # 落盘间隔（秒）
WATCH_LOG_MAX_BYTES = 8 * 1024 * 1024   # perf_threads.log 上限（超出裁剪，防长时间膨胀）
WATCH_LOG_KEEP_BYTES = 1 * 1024 * 1024  # 裁剪后保留的尾部字节数

_watch_lock = threading.Lock()
_watch_history = deque(maxlen=20)   # [(ts, [stack_lines])]
_watch_thread = None
_watch_stop = threading.Event()
LAST_HEARTBEAT = None       # 主线程心跳时间戳（由 UI 主循环打点）
_last_disk_ts = 0.0


def heartbeat():
    """由 UI 主线程定时调用，记录主线程仍存活的最新时刻。"""
    global LAST_HEARTBEAT
    LAST_HEARTBEAT = time.time()


def _format_stack(frame, limit=25):
    lines = []
    f = frame
    while f is not None and len(lines) < limit:
        co = f.f_code
        lines.append(f"{co.co_name} ({co.co_filename}:{f.f_lineno})")
        f = f.f_back
    return lines


def _main_frame():
    """返回主线程 (threading.main_thread) 的顶部 frame，供取栈。"""
    frames = sys._current_frames()
    main_tid = threading.main_thread().ident
    return frames.get(main_tid)


def _watchdog_loop():
    global _last_disk_ts
    while not _watch_stop.is_set():
        try:
            frame = _main_frame()
            if frame is not None:
                with _watch_lock:
                    _watch_history.append((time.time(), _format_stack(frame)))
        except Exception:
            pass
        # 定期落盘（即使进程冻结，只要守护线程还活着就能持续写盘）
        now = time.time()
        if now - _last_disk_ts >= WATCH_DISK_EVERY:
            _last_disk_ts = now
            _dump_history_to_disk(history=None)
        _watch_stop.wait(WATCH_INTERVAL)


def _dump_history_to_disk(history=None):
    try:
        os.makedirs(PERF_LOG_DIR, exist_ok=True)
        rows = history if history is not None else _snapshot_history()
        lines = [f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ==="]
        for ts, stack in rows:
            lines.append(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}]")
            lines.extend(stack or ["<no frame>"])
        with open(WATCH_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        _trim_watch_log()
    except Exception:
        pass


def _trim_watch_log():
    """perf_threads.log 超出上限时保留尾部并打标记，防止 5 秒落盘长期膨胀。"""
    try:
        if os.path.getsize(WATCH_LOG) <= WATCH_LOG_MAX_BYTES:
            return
        with open(WATCH_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(WATCH_LOG) - WATCH_LOG_KEEP_BYTES))
            tail = f.read()
        cut = tail.find(b"\n")          # 对齐到行首，避免半个栈帧
        if cut >= 0:
            tail = tail[cut + 1:]
        with open(WATCH_LOG, "wb") as f:
            f.write(b"=== perf_threads.log trimmed (size cap) ===\n")
            f.write(tail)
    except Exception:
        pass


def _snapshot_history():
    with _watch_lock:
        return list(_watch_history)


def start_watchdog():
    """启动常驻守护线程：持续记录主线程调用栈（含落盘），用于卡死排查。"""
    global _watch_thread
    if _watch_thread is not None and _watch_thread.is_alive():
        return
    _watch_stop.clear()
    _watch_thread = threading.Thread(target=_watchdog_loop, name="perf-watchdog",
                                     daemon=True)
    _watch_thread.start()


def stop_watchdog():
    _watch_stop.set()


def watchdog_alive():
    return _watch_thread is not None and _watch_thread.is_alive()


# 返回最近一次抓取的主线程栈 + 心跳信息
def main_thread_signal():
    hist = _snapshot_history()
    last_ts, last_stack = (hist[-1] if hist else (None, None))
    return {
        "heartbeat_ts": LAST_HEARTBEAT,
        "last_capture_ts": last_ts,
        "last_stack": last_stack or [],
        "captures": len(hist),
        "watchdog_alive": watchdog_alive(),
    }


def read_disk_signal():
    """读取磁盘上残留的运行记录（上次卡死留下的线索），返回最新一段。"""
    try:
        with open(WATCH_LOG, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return ""
        # 取最后 ~40 行
        return "\n".join(text.splitlines()[-40:])
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
