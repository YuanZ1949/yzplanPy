"""MCP JSON-RPC 协议层：消息处理与工具调用分发。

顶层仅依赖标准库；TOOLS 聚合表由 mcp_server/__init__.py 构建，
协议层在函数体内延迟导入以避免包初始化循环依赖。
"""

import json
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "yzplan-mcp"
SERVER_VERSION = "1.0.0"


def _log(*args):
    # 协议错误/诊断写入 stderr，避免污染 stdout
    print("[mcp]", *args, file=sys.stderr)


def _content_text(*lines):
    return [{"type": "text", "text": "\n".join(str(l) for l in lines)}]


# ── MCP JSON-RPC 处理 ─────────────────────────────────────────────────

def _make_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


_TOOL_ERROR_CODE = -32602
_INTERNAL_ERROR_CODE = -32603


def _call_tool(name, args):
    from . import _TOOL_BY_NAME  # 延迟导入：TOOLS 由 __init__ 聚合，避免循环导入
    tool = _TOOL_BY_NAME.get(name)
    if not tool:
        raise ValueError(f"未知工具: {name}")
    try:
        return tool["handler"](args or {})
    except Exception as e:  # noqa: BLE001
        _log("工具调用失败", name, e)
        raise


def handle_message(msg):
    """处理单个 MCP JSON-RPC 消息，返回响应（dict）或 None（纯通知）。"""
    from . import TOOLS  # 延迟导入：TOOLS 由 __init__ 聚合，避免循环导入
    if not isinstance(msg, dict):
        return None
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return _make_result(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _make_result(mid, {})
    if method == "tools/list":
        public_tools = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]
        return _make_result(mid, {"tools": public_tools})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = _call_tool(name, args)
        except KeyError:
            return _make_error(mid, _TOOL_ERROR_CODE, f"未知工具: {name}")
        except ValueError as e:
            return _make_error(mid, _TOOL_ERROR_CODE, str(e))
        except Exception as e:  # noqa: BLE001
            _log("工具调用内部错误", name, e)
            return _make_error(mid, _INTERNAL_ERROR_CODE, f"工具调用失败: {e}")
        return _make_result(mid, {
            "content": _content_text(json.dumps(result, ensure_ascii=False, default=str)),
            "isError": False,
        })
    return _make_error(mid, -32601, f"不支持的方法: {method}")