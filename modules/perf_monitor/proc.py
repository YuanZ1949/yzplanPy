"""perf_monitor 进程资源：_PROC/_proc_resources/_num_handles。"""
import time
_PROC = None  # 复用的 psutil.Process 实例，保证 cpu_percent 能跨次计算
_LAST_CPU_TS = None   # 上次 cpu_percent 采样的墙钟时刻（monotonic）
_LAST_CPU_VAL = 0.0   # 最近一次有效 CPU 读数（首次调用/长间隔后沿用）
_CPU_MAX_GAP = 5.0    # 两次采样间隔超过该秒数视为窗口失效（定时器暂停/窗口隐藏）


def _reset_cpu_state():
    """重置 CPU 采样基线（进程更换 / 测试用）。"""
    global _LAST_CPU_TS, _LAST_CPU_VAL
    _LAST_CPU_TS = None
    _LAST_CPU_VAL = 0.0


def _proc_resources():
    global _PROC, _LAST_CPU_TS, _LAST_CPU_VAL
    import psutil
    if _PROC is None or _PROC.pid != psutil.Process().pid:
        _PROC = psutil.Process()
        _reset_cpu_state()
    p = _PROC
    mem = p.memory_info()
    cpu = 0.0
    if hasattr(p, "cpu_percent"):
        now = time.monotonic()
        if _LAST_CPU_TS is None:
            # 首次调用：cpu_percent 无基线返回 0.0，属无意义读数，
            # 仅建立基线并沿用上次有效值（默认 0.0）。
            p.cpu_percent(interval=None)
            _LAST_CPU_TS = now
            cpu = _LAST_CPU_VAL
        else:
            gap = now - _LAST_CPU_TS
            _LAST_CPU_TS = now
            raw = p.cpu_percent(interval=None)
            if gap <= _CPU_MAX_GAP:
                # 间隔正常：读数有效，更新缓存值。
                _LAST_CPU_VAL = raw
                cpu = raw
            else:
                # 间隔过长（定时器暂停/窗口隐藏后恢复）：该读数跨度过大，
                # 丢弃并沿用上次有效值；本次调用已重置 psutil 基线，
                # 下一次调用即为新鲜读数。
                cpu = _LAST_CPU_VAL
    return {
        "pid": p.pid,
        "cpu": cpu,
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
            return win32process.GetProcessHandleCount(h)[1]  # type: ignore[reportAttributeAccessIssue]
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return 0
