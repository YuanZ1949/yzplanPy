"""MCP 工具切片：GUI 导航与系统工具 (gui_*/system_*/app_restart)。

除 system_version / system_autostart 外均经 mcp_inbox IPC 请求 GUI
（函数内 lazy import tools_system_config_gui._mcp_inbox_command）。
"""

import json
import os
import time
import uuid


# ── GUI 导航与系统工具 ────────────────────────────────────────────────

def gui_show_window():
    """请求 GUI 显示主窗口。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("show_window", {"title": "YZplan", "message": "MCP 请求显示窗口", "silent": True})


def gui_navigate(module_id):
    """请求 GUI 跳转到指定模块页面。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("navigate_module", {
        "module_id": str(module_id), "title": "YZplan", "message": f"跳转到 {module_id}", "silent": True})


def gui_export_logs():
    """请求 GUI 导出日志到文件（通过 mcp_inbox IPC）。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("export_logs", {"title": "日志导出", "message": "MCP 请求导出日志"})


def gui_quit():
    """请求 GUI 退出程序。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("quit", {"title": "YZplan 退出", "message": "MCP 请求退出程序", "level": "warning"})


def system_version():
    """获取应用版本号。"""
    from core.constants import APP_VERSION
    return {"version": APP_VERSION, "name": "YZplan"}


def system_autostart():
    """查询当前开机自启状态。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        try:
            val, _ = winreg.QueryValueEx(key, "YZplan")
            winreg.CloseKey(key)
            return {"enabled": True, "value": val}
        except FileNotFoundError:
            winreg.CloseKey(key)
            return {"enabled": False}
    except Exception:
        return {"enabled": False, "error": "无法读取注册表"}


# ── GUI 通知控制 ──────────────────────────────────────────────────────

def gui_notify(title, message="", level="info"):
    """写一条通知到 mcp_inbox，由运行中的 GUI 轮询弹出托盘通知。"""
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "id": uuid.uuid4().hex,
        "title": str(title),
        "message": str(message),
        "level": str(level),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    # 若 GUI 开启了 MCP inbox 监听，这里即可被唤醒
    return {"queued": True, "inbox_file": path}


def app_restart(delay_seconds=2):
    """请求运行中的 GUI 完全重启（退出并重新拉起 main.py）。

    通过把带 command=restart 的命令写入 mcp_inbox，由 GUI 主线程的监听器执行
    core.restart.restart_app()。返回排队结果。
    """
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "id": uuid.uuid4().hex,
        "command": "restart",
        "delay_seconds": int(delay_seconds or 0),
        "title": "YZplan 重启",
        "message": "MCP 请求重启程序，请稍候…",
        "level": "warning",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return {"queued": True, "command": "restart", "inbox_file": path}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "gui_show_window",
        "description": "请求 GUI 显示主窗口（通过 mcp_inbox IPC）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: gui_show_window(),
    },
    {
        "name": "gui_navigate",
        "description": "请求 GUI 跳转到指定模块页面（通过 mcp_inbox IPC）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "必填，模块 ID（如 rss_aggregator）"},
            },
            "required": ["module_id"],
        },
        "handler": lambda a: gui_navigate(a["module_id"]),
    },
    {
        "name": "gui_export_logs",
        "description": "请求 GUI 导出运行日志到文件（通过 mcp_inbox IPC）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: gui_export_logs(),
    },
    {
        "name": "gui_quit",
        "description": "请求 GUI 退出程序（通过 mcp_inbox IPC）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: gui_quit(),
    },
    {
        "name": "system_version",
        "description": "获取 YZplan 应用版本号。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: system_version(),
    },
    {
        "name": "system_autostart",
        "description": "查询当前开机自启注册表状态。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: system_autostart(),
    },
    {
        "name": "gui_notify",
        "description": "向正在运行的 YZplan GUI 发送一条系统托盘通知（若应用未运行则仅入队）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "必填，通知标题"},
                "message": {"type": "string", "description": "通知内容"},
                "level": {"type": "string", "description": "info/success/warning/error"},
            },
            "required": ["title"],
        },
        "handler": lambda a: gui_notify(a["title"], message=a.get("message", ""), level=a.get("level", "info")),
    },
    {
        "name": "app_restart",
        "description": "请求正在运行的 YZplan GUI 完全重启（退出并重新拉起 main.py）。" \
                       "会把 restart 命令写入 mcp_inbox，由 GUI 主线程执行重启，随后 MCP 端口会短暂断开。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delay_seconds": {"type": "integer", "description": "可选，延迟重启秒数（默认 2）"},
            },
        },
        "handler": lambda a: app_restart(delay_seconds=a.get("delay_seconds", 2)),
    },
]