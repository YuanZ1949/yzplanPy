"""perf_monitor 进程资源：_PROC/_proc_resources/_num_handles。"""
import time
_PROC = None  # 复用的 psutil.Process 实例，保证 cpu_percent 能跨次计算


def _proc_resources():
    global _PROC
    import psutil
    if _PROC is None or _PROC.pid != psutil.Process().pid:
        _PROC = psutil.Process()
    p = _PROC
    mem = p.memory_info()
    return {
        "pid": p.pid,
        "cpu": p.cpu_percent(interval=None) if hasattr(p, "cpu_percent") else 0.0,
        "memory_mb": round(mem.rss / (1024 * 1024), 1),
        "threads": p.num_threads() if hasattr(p, "num_threads") else 0,
        "handles": _num_handles(p.pid),
        "uptime_s": int(time.time() - p.create_time()) if hasattr(p, "create_time") else 0,
    }


def _num_handles(pid):
    try:
        import win32process
        import win32api
        h = win32api.OpenProcess(0x0400, False, pid)
        try:
            return win32process.GetProcessHandleCount(h)[1]
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return 0
