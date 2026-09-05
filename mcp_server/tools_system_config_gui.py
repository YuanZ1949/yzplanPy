"""MCP 工具切片：系统信息/日志 + 配置/模块 (system_*/logs_*/config_*/module_*)。

包含共享辅助 `_config_path`/`_load_config`/`_mcp_inbox_command`，供其他切片
（tools_webview / tools_gui / tools_rss_advanced 经 mcp_inbox IPC 请求 GUI）函数内 lazy 复用。
"""

import json
import os
import time
import uuid


# ── 系统信息 ──────────────────────────────────────────────────────────

def system_info():
    from modules.sys_info import collect_info
    return collect_info()


def system_resources():
    import psutil
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory_percent": vm.percent,
        "memory_used_gb": round(vm.used / (1024 ** 3), 2),
        "memory_total_gb": round(vm.total / (1024 ** 3), 2),
    }


# ── 日志查询 ──────────────────────────────────────────────────────────

def logs_get(level=None, keyword=None, limit=200):
    from core.logger import get_memory_logs
    return list(get_memory_logs(level=level, keyword=keyword, limit=int(limit)))


def logs_clear():
    from core.logger import clear_memory_logs, reset_error_count
    clear_memory_logs()
    reset_error_count()
    return {"cleared": True}


# ── 配置读写 ──────────────────────────────────────────────────────────

def _config_path():
    from core.constants import DATA_DIR, CONFIG_PATH
    os.makedirs(DATA_DIR, exist_ok=True)
    return CONFIG_PATH


def _load_config():
    p = _config_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def config_get(key=None):
    data = _load_config()
    if not key:
        return data
    cur = data
    for part in str(key).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _mcp_inbox_command(command, extra=None):
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "id": uuid.uuid4().hex,
        "command": command,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "silent": True,
    }
    if extra:
        payload.update(extra)
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return {"queued": True, "command": command, "inbox_file": path}


def config_set(key, value):
    data = _load_config()
    parts = str(key).split(".")
    cur = data
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return {"set": True, "key": key, "value": value}


def module_list():
    data = _load_config()
    modules = data.get("modules", {})
    result = []
    for mid, mcfg in modules.items():
        result.append({
            "id": mid,
            "enabled": mcfg.get("enabled", True),
            "config": mcfg.get("config", {}),
        })
    return result


def module_enable(module_id):
    return _mcp_inbox_command("toggle_module", {"module_id": str(module_id), "enabled": True})


def module_disable(module_id):
    return _mcp_inbox_command("toggle_module", {"module_id": str(module_id), "enabled": False})


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS_SYSTEM_LOGS = [
    {
        "name": "system_info",
        "description": "读取电脑硬件/系统配置信息（主机名、系统、CPU、内存、GPU、磁盘）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: system_info(),
    },
    {
        "name": "system_resources",
        "description": "读取实时系统资源占用（CPU 百分比、内存百分比/容量）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: system_resources(),
    },
    {
        "name": "logs_get",
        "description": "查询 YZplan 应用在内存中的运行日志，可按级别、关键词过滤。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "description": "DEBUG/INFO/WARNING/ERROR/CRITICAL"},
                "keyword": {"type": "string"},
                "limit": {"type": "integer", "description": "条数上限"},
            },
        },
        "handler": lambda a: logs_get(level=a.get("level"), keyword=a.get("keyword"), limit=a.get("limit", 200)),
    },
    {
        "name": "logs_clear",
        "description": "清空内存日志与错误计数。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: logs_clear(),
    },
]

TOOLS_CONFIG_MODULES = [
    {
        "name": "config_get",
        "description": "读取应用配置。不传 key 返回全部配置；传 dot-path（如 'rss.proxy'）返回对应值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "dot-path 配置键，如 'ui.theme'、'rss.proxy'、'autostart'"},
            },
        },
        "handler": lambda a: config_get(key=a.get("key")),
    },
    {
        "name": "config_set",
        "description": "写入应用配置（直接修改 settings.json，下次启动生效；部分设置可通过 IPC 通知 GUI 即时生效）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "必填，dot-path 配置键"},
                "value": {"description": "必填，配置值"},
            },
            "required": ["key", "value"],
        },
        "handler": lambda a: config_set(a["key"], a["value"]),
    },
    {
        "name": "module_list",
        "description": "列出所有已注册模块及其启用状态和配置。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: module_list(),
    },
    {
        "name": "module_enable",
        "description": "启用指定模块（通过 mcp_inbox IPC 通知 GUI，需要 GUI 正在运行）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "必填，模块 ID"},
            },
            "required": ["module_id"],
        },
        "handler": lambda a: module_enable(a["module_id"]),
    },
    {
        "name": "module_disable",
        "description": "禁用指定模块（通过 mcp_inbox IPC 通知 GUI，需要 GUI 正在运行）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "必填，模块 ID"},
            },
            "required": ["module_id"],
        },
        "handler": lambda a: module_disable(a["module_id"]),
    },
]

TOOLS = TOOLS_SYSTEM_LOGS + TOOLS_CONFIG_MODULES