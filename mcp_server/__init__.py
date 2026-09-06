"""YZplan MCP 服务器。

通过 Model Context Protocol (MCP) 提供对 YZplan 数据和功能的访问接口：
便签/待办 CRUD、系统信息、日志查询、RSS 管理、GUI 通知控制。

传输方式：
  - stdio：python -m mcp_server stdio
  - HTTP/SSE：python -m mcp_server http --host 127.0.0.1 --port 8765

GUI 通知通过写入 DATA_DIR/mcp_inbox/*.json 由正在运行的 GUI 轮询后弹出系统托盘通知。
"""

import argparse
import os
import sys

# 让 stdio 模式下的日志不要污染 MCP 协议输出（MCP 用 stdout 传输 JSON-RPC）
_imported = False
if not _imported:
    _imported = True
    _in_mcp = "mcp" in sys.argv[0] or "mcp_server" in sys.argv[0]

# 包化后 __file__ 位于 mcp_server/ 内，仍需向仓库根目录插入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 工具切片聚合 ───────────────────────────────────────────────────────
# 各切片文件分类维护 handler 与 TOOLS 定义；此处按原 mcp_server.py 的
# TOOLS 顺序拼接，保证 tools/list 输出顺序与改前逐字节一致。

from . import (  # noqa: E402
    tools_gui,
    tools_perf,
    tools_rss_advanced,
    tools_rss_agg,
    tools_rss_feeds,
    tools_rss_items,
    tools_rss_rules,
    tools_screenshot,
    tools_system_config_gui,
    tools_todo,
    tools_webview,
)

TOOLS = (
    tools_todo.TOOLS
    + tools_system_config_gui.TOOLS_SYSTEM_LOGS
    + tools_rss_feeds.TOOLS
    + tools_rss_items.TOOLS
    + tools_rss_agg.TOOLS
    + tools_rss_rules.TOOLS
    + tools_system_config_gui.TOOLS_CONFIG_MODULES
    + tools_rss_advanced.TOOLS
    + tools_webview.TOOLS
    + tools_gui.TOOLS
    + tools_perf.TOOLS
    + tools_screenshot.TOOLS
)

_TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


# ── 数据访问层（直接读写 SQLite，不依赖 GUI）───────────────────────────
# 保留原 _dbs 辅助（历史兼容；切片内的 _db_path 在 tools_rss_feeds 中）。

def _dbs():
    from core.constants import DB_PATH, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)


# ── 协议层与传输层 ─────────────────────────────────────────────────────

from .protocol import (  # noqa: E402
    _call_tool,
    _content_text,
    _log,
    _make_error,
    _make_result,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    handle_message,
)
from .transport import _as_json, _http_handler, run_http, run_stdio  # noqa: E402


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="mcp_server", description="YZplan MCP Server")
    parser.add_argument("transport", nargs="?", default="stdio", choices=["stdio", "http"],
                        help="传输方式，默认 stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.transport == "http":
        run_http(args.host, args.port)
    else:
        run_stdio()