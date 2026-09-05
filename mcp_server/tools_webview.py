"""MCP 工具切片：WebView2 控制 (webview_*)。

webview_kill / webview_scan 经 mcp_inbox IPC 请求 GUI 执行
（函数内 lazy import tools_system_config_gui._mcp_inbox_command）。
"""


# ── WebView2 控制 ─────────────────────────────────────────────────────

def webview_list():
    """列出当前运行的 WebView2 相关进程。"""
    import subprocess
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedgewebview2.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and "INFO" not in l]
        processes = []
        for line in lines:
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 5:
                processes.append({"name": parts[0], "pid": parts[1], "session": parts[2],
                                  "mem_usage": parts[4] if len(parts) > 4 else ""})
        return {"processes": processes, "count": len(processes)}
    except Exception as e:
        return {"processes": [], "count": 0, "error": str(e)}


def webview_block(host_or_path):
    """添加 WebView2 防火墙拦截规则。"""
    from modules.webview_control import block_remote_ip
    return block_remote_ip(host_or_path)


def webview_unblock(name):
    """删除指定的 WebView2 防火墙拦截规则。"""
    from modules.webview_control import unblock_rule
    return unblock_rule(name)


def webview_kill():
    """终止所有 WebView2 进程（通过 mcp_inbox IPC 让 GUI 执行，以确保权限正确）。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("webview_kill", {"title": "WebView2", "message": "MCP 请求终止 WebView2 进程"})


def webview_scan():
    """请求 GUI 扫描 WebView2 程序列表（通过 mcp_inbox IPC）。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("scan_webview", {"title": "WebView2 扫描", "message": "MCP 请求扫描 WebView2"})


def webview_rules():
    """获取当前所有 YZplan 相关的防火墙规则。"""
    from modules.webview_control import list_yzplan_rules
    return list_yzplan_rules()


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "webview_list",
        "description": "列出当前运行的 WebView2 相关进程。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: webview_list(),
    },
    {
        "name": "webview_block",
        "description": "添加 Windows 防火墙出站拦截规则。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host_or_path": {"type": "string", "description": "必填，IP 地址或程序路径"},
            },
            "required": ["host_or_path"],
        },
        "handler": lambda a: webview_block(a["host_or_path"]),
    },
    {
        "name": "webview_unblock",
        "description": "删除指定的 Windows 防火墙拦截规则。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "必填，规则名称标识"},
            },
            "required": ["name"],
        },
        "handler": lambda a: webview_unblock(a["name"]),
    },
    {
        "name": "webview_kill",
        "description": "请求终止所有 WebView2 进程（通过 mcp_inbox IPC 让 GUI 执行）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: webview_kill(),
    },
    {
        "name": "webview_scan",
        "description": "请求 GUI 扫描 WebView2 程序列表（通过 mcp_inbox IPC）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: webview_scan(),
    },
    {
        "name": "webview_rules",
        "description": "获取当前所有 YZplan 相关的 Windows 防火墙出站规则。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: webview_rules(),
    },
]