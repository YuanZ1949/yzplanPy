"""core/perf: 线程实时栈快照（Python 帧 + psutil 原生线程）。"""

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
