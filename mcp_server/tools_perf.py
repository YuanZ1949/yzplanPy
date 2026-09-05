"""MCP 工具切片：性能监测 (perf_*)。

通过 mcp_inbox/mcp_outbox 请求运行中的 GUI 上报其内存中的耗时统计；
GUI 未运行或超时则回退到 MCP 自身进程的 core.perf 统计。
"""

import json
import os
import time
import uuid


# ── 性能监测（诊断卡死/热点）────────────────────────────────────────────

# 通过 mcp_inbox 请求 GUI 进程上报其内存中的耗时统计所需参数。
_PERF_GUI_REQ_COMMAND = "perf_stats_request"
_PERF_GUI_TIMEOUT = 2.5      # 等待 GUI 回复的秒数（对应托盘 2s 轮询 + 余量）


def _gui_perf_snapshot():
    """请求运行中的 GUI 进程上报它的 core.perf 统计（其图表数据源）。

    返回 dict（含 rows/enabled/uptime_s）或 None（GUI 未运行 / 超时无回复）。
    """
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    outbox = os.path.join(DATA_DIR, "mcp_outbox")
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(outbox, exist_ok=True)
    req_id = uuid.uuid4().hex
    reply_path = os.path.join(outbox, f"perf_stats_{req_id}.json")
    payload = {
        "id": req_id,
        "command": _PERF_GUI_REQ_COMMAND,
        "reply_file": reply_path,
        "silent": True,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    req_path = os.path.join(inbox, f"{req_id}.json")
    try:
        with open(req_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        return None

    deadline = time.time() + _PERF_GUI_TIMEOUT
    try:
        while time.time() < deadline:
            time.sleep(0.2)
            if os.path.isfile(reply_path):
                try:
                    with open(reply_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data
                except Exception:
                    return None
                finally:
                    try:
                        os.remove(reply_path)
                    except OSError:
                        pass
    finally:
        # 清理未消费的请求文件：GUI 未运行或已错过轮询时避免残留堆积
        try:
            os.remove(req_path)
        except OSError:
            pass
    return None


def perf_stats():
    """返回性能监测模块采集的函数/操作耗时统计（热点定位）。

    优先请求运行中的 GUI 进程上报其界面图表所用的内存统计（数据源与
    GUI 面板一致）；若 GUI 未运行或超时，则回退到 MCP 自身进程的统计。
    """
    from core import perf
    gui = _gui_perf_snapshot()
    if gui and isinstance(gui.get("rows"), list):
        return {
            "enabled": bool(gui.get("enabled", perf.is_enabled())),
            "uptime_s": round(float(gui.get("uptime_s", 0.0)), 1),
            "rows": gui["rows"],
            "source": "gui",
        }
    enabled = perf.is_enabled()
    rows = perf.stats()
    return {"enabled": enabled, "uptime_s": round(perf.uptime_seconds(), 1),
            "rows": rows, "source": "local"}


def perf_threads():
    """抓取当前进程各线程正在执行的函数栈快照（用于定位卡死/死锁现场）。"""
    from core import perf
    return {"threads": perf.thread_snapshots()}


def perf_profile(take_snapshot=True):
    """读取/控制系统级函数采样器。"""
    from core import perf
    if take_snapshot:
        return {"running": getattr(perf, "_profiler_enabled", False),
                "functions": perf.profile_snapshot()}
    return {"running": getattr(perf, "_profiler_enabled", False)}


def perf_enable(on=True):
    """开关 core.perf 耗时采集。"""
    from core import perf
    perf.set_enabled(bool(on))
    return {"enabled": perf.is_enabled()}


def perf_reset():
    """清空 core.perf 采集的数据。"""
    from core import perf
    perf.reset()
    return {"reset": True}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "perf_threads",
        "description": "抓取当前进程各线程正在执行的函数栈快照，用于诊断程序卡死/死锁现场（这是诊断关键工具）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: perf_threads(),
    },
    {
        "name": "perf_stats",
        "description": "查看性能监测模块采集的函数/操作耗时统计（热点定位）。优先请求运行中的 GUI 进程上报其界面图表所用的内存统计数据源；GUI 未运行时回退到 MCP 自身进程统计。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: perf_stats(),
    },
    {
        "name": "perf_profile",
        "description": "读取系统级函数采样器的当前函数热点统计。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: perf_profile(),
    },
    {
        "name": "perf_enable",
        "description": "开关性能耗时采集（on=true 开启，false 关闭）。",
        "inputSchema": {"type": "object",
                        "properties": {"on": {"type": "boolean", "description": "是否开启采集"}}},
        "handler": lambda a: perf_enable(a.get("on", True)),
    },
    {
        "name": "perf_reset",
        "description": "清空性能监测已采集的数据。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: perf_reset(),
    },
]