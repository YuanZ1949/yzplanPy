"""core/perf: 卡死排查守护线程 + 主线程飞行记录 + 磁盘落盘。"""
import os
import sys
import threading
import time
from collections import deque
from .constants import PERF_LOG_DIR

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
