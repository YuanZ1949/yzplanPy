"""core/perf: 系统级函数采样器（sys.setprofile）。"""
import sys
import threading
import time

# 模块级状态（原 core/perf.py 中与 _cprofile/_profiler_enabled 相关的
# 初始化值，拆包后收归此切片以保证 profile_* 首调可读）。
_cprofile = None
_profiler_enabled = False

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
