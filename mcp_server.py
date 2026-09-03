"""YZplan MCP 服务器。

通过 Model Context Protocol (MCP) 提供对 YZplan 数据和功能的访问接口：
便签/待办 CRUD、系统信息、日志查询、RSS 管理、GUI 通知控制。

传输方式：
  - stdio：python mcp_server.py stdio
  - HTTP/SSE：python mcp_server.py http --host 127.0.0.1 --port 8765

GUI 通知通过写入 DATA_DIR/mcp_inbox/*.json 由正在运行的 GUI 轮询后弹出系统托盘通知。
"""

import argparse
import json
import os
import sys
import threading
import time
import uuid

# 让 stdio 模式下的日志不要污染 MCP 协议输出（MCP 用 stdout 传输 JSON-RPC）
_imported = False
if not _imported:
    _imported = True
    _in_mcp = "mcp" in sys.argv[0] or "mcp_server" in sys.argv[0]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "yzplan-mcp"
SERVER_VERSION = "1.0.0"


def _log(*args):
    # 协议错误/诊断写入 stderr，避免污染 stdout
    print("[mcp]", *args, file=sys.stderr)


# ── 数据访问层（直接读写 SQLite，不依赖 GUI）───────────────────────────

def _db_path():
    from core.constants import DB_PATH, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    return DB_PATH


def _dbs():
    from core.constants import DB_PATH, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)


# ── 便签/待办 ─────────────────────────────────────────────────────────

def _todo_find(id_):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, title, content, priority, category, done, due_date, created_at, updated_at "
        "FROM todo_notes WHERE id=?", (id_,)).fetchone()
    conn.close()
    return dict(row) if row else None


def todo_add(title, content="", priority=1, due_date=None, category=""):
    import sqlite3
    from datetime import datetime
    if not title or not str(title).strip():
        raise ValueError("title 不能为空")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(_db_path())
    cur = conn.execute(
        "INSERT INTO todo_notes (title, content, priority, category, done, due_date, created_at, updated_at) "
        "VALUES (?,?,?,?,0,?,?,?)",
        (str(title).strip(), str(content or ""), int(priority), str(category or ""),
         due_date or None, now, now))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return todo_list(todo_id=tid)


def todo_list(done=None, keyword=None, category=None, order="created_at", limit=500, todo_id=None):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    q = ("SELECT id, title, content, priority, category, done, due_date, created_at, updated_at "
         "FROM todo_notes")
    cond, params = [], []
    if todo_id is not None:
        cond.append("id = ?")
        params.append(int(todo_id))
    if done is not None:
        if str(done).lower() in ("1", "true", "done", "yes", "已完成"):
            done = 1
        elif str(done).lower() in ("0", "false", "pending", "no", "待办", "未完成"):
            done = 0
        else:
            done = int(done)
        cond.append("done = ?")
        params.append(done)
    if keyword:
        cond.append("(title LIKE ? OR content LIKE ?)")
        kw = f"%{keyword}%"
        params += [kw, kw]
    if category:
        cond.append("category = ?")
        params.append(str(category))
    if cond:
        q += " WHERE " + " AND ".join(cond)
    om = {"created_at": "created_at DESC", "priority": "priority DESC, created_at DESC",
          "due_date": "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC", "id": "id ASC"}
    q += f" ORDER BY {om.get(str(order), 'created_at DESC')} LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def todo_update(id_, **_kwargs):
    import sqlite3
    from datetime import datetime
    cur_todo = _todo_find(id_)
    if not cur_todo:
        raise ValueError(f"找不到 id={id_} 的待办")
    allowed = ("title", "content", "priority", "category", "done", "due_date")
    sets, params = [], []
    for k in allowed:
        if k in _kwargs:
            sets.append(f"{k} = ?")
            params.append(_kwargs[k])
    if not sets:
        return cur_todo
    params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    params.append(int(id_))
    conn = sqlite3.connect(_db_path())
    conn.execute(f"UPDATE todo_notes SET {', '.join(sets)}, updated_at=? WHERE id=?", params)
    conn.commit()
    conn.close()
    return todo_list(todo_id=id_)


def todo_delete(id_):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.execute("DELETE FROM todo_notes WHERE id=?", (int(id_),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def todo_stats():
    conn = None
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) c FROM todo_notes").fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) c FROM todo_notes WHERE done=1").fetchone()["c"]
    pending = total - done
    conn.close()
    return {"total": total, "done": done, "pending": pending}


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


# ── RSS 管理 ──────────────────────────────────────────────────────────

def _rss_store():
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    # 确保表存在（复用 rss_store 的表结构）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feeds(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            tag TEXT, enabled INTEGER DEFAULT 1,
            group_name TEXT DEFAULT '',
            refresh_interval INTEGER DEFAULT 1800,
            last_refresh TEXT, custom_headers TEXT DEFAULT '{}',
            etag TEXT DEFAULT '', last_modified TEXT DEFAULT '',
            last_error TEXT DEFAULT '', error_count INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        );
    """)
    return conn


def rss_list():
    conn = _rss_store()
    rows = conn.execute("SELECT * FROM feeds ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_add(name, url, tag="", group_name="", enabled=True):
    conn = _rss_store()
    try:
        cur = conn.execute(
            "INSERT INTO feeds(name, url, tag, group_name, enabled) VALUES (?,?,?,?,?)",
            (str(name).strip(), str(url).strip(), tag, group_name, int(bool(enabled))))
        conn.commit()
        fid = cur.lastrowid
    except sqlite3.IntegrityError as e:
        conn.close()
        raise ValueError(f"新增 RSS 失败（可能名称重复）：{e}")
    conn.close()
    return rss_list_by_id(fid)


def rss_list_by_id(fid):
    conn = _rss_store()
    row = conn.execute("SELECT * FROM feeds WHERE id=?", (int(fid),)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_update(fid, **_kwargs):
    conn = _rss_store()
    row = conn.execute("SELECT id FROM feeds WHERE id=?", (int(fid),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 id={fid} 的 RSS 源")
    allowed = ("name", "url", "tag", "group_name", "enabled", "refresh_interval")
    sets, params = [], []
    for k in allowed:
        if k in _kwargs:
            sets.append(f"{k} = ?")
            params.append(_kwargs[k])
    if sets:
        params.append(int(fid))
        conn.execute(f"UPDATE feeds SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    conn.close()
    return rss_list_by_id(fid)


def rss_delete(fid):
    conn = _rss_store()
    conn.execute("DELETE FROM feeds WHERE id=?", (int(fid),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def rss_recent(limit=20):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT hash, title, link, published FROM items ORDER BY published DESC LIMIT ?",
            (int(limit),)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


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


# ── 性能监测（诊断卡死/热点）────────────────────────────────────────────

def perf_stats():
    """返回 core.perf 采集的函数/操作耗时统计（用于定位卡顿热点）。"""
    from core import perf
    enabled = perf.is_enabled()
    rows = perf.stats()
    return {"enabled": enabled, "uptime_s": round(perf.uptime_seconds(), 1),
            "rows": rows}


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

def _content_text(*lines):
    return [{"type": "text", "text": "\n".join(str(l) for l in lines)}]


TOOLS = [
    {
        "name": "todo_list",
        "description": "查询便签/待办列表。可按完成状态、关键词、类别筛选并排序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "done": {"type": ["boolean", "integer", "string"],
                         "description": "筛选：true/1/已完成... 或 false/0/待办..."},
                "keyword": {"type": "string", "description": "按标题/内容关键词搜索"},
                "category": {"type": "string", "description": "按类别筛选"},
                "order": {"type": "string", "description": "排序：created_at/priority/due_date/id"},
                "limit": {"type": "integer", "description": "返回条数上限"},
            },
        },
        "handler": lambda a: todo_list(
            done=a.get("done"), keyword=a.get("keyword"), category=a.get("category"),
            order=a.get("order", "created_at"), limit=a.get("limit", 500)),
    },
    {
        "name": "todo_add",
        "description": "新增一条便签/待办。返回创建后的完整记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "必填，标题"},
                "content": {"type": "string", "description": "内容"},
                "priority": {"type": "integer", "description": "优先级 0低/1中/2高/3紧急"},
                "due_date": {"type": "string", "description": "截止日期 YYYY-MM-DD"},
                "category": {"type": "string", "description": "类别"},
            },
            "required": ["title"],
        },
        "handler": lambda a: todo_add(
            a["title"], content=a.get("content", ""), priority=a.get("priority", 1),
            due_date=a.get("due_date"), category=a.get("category", "")),
    },
    {
        "name": "todo_update",
        "description": "更新一条便签/待办（只更新传入的字段）。返回更新后的记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "便签 id"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "priority": {"type": "integer", "description": "0低/1中/2高/3紧急"},
                "category": {"type": "string"},
                "done": {"type": ["boolean", "integer"], "description": "是否完成"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD 或空字符串清除"},
            },
            "required": ["id"],
        },
        "handler": lambda a: todo_update(int(a["id"]), **{k: v for k, v in a.items() if k != "id"}),
    },
    {
        "name": "todo_delete",
        "description": "删除一条便签/待办。",
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "integer", "description": "便签 id"}},
                        "required": ["id"]},
        "handler": lambda a: todo_delete(a["id"]),
    },
    {
        "name": "todo_stats",
        "description": "统计待办总数、已完成、未完成。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: todo_stats(),
    },
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
    {
        "name": "rss_list",
        "description": "列出所有 RSS 订阅源。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_list(),
    },
    {
        "name": "rss_add",
        "description": "新增一个 RSS 订阅源。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "必填，源名称"},
                "url": {"type": "string", "description": "必填，源地址"},
                "tag": {"type": "string", "description": "标签"},
                "group_name": {"type": "string", "description": "分组"},
                "enabled": {"type": "boolean", "description": "是否启用"},
            },
            "required": ["name", "url"],
        },
        "handler": lambda a: rss_add(a["name"], a["url"], tag=a.get("tag", ""),
                                     group_name=a.get("group_name", ""), enabled=a.get("enabled", True)),
    },
    {
        "name": "rss_update",
        "description": "更新一个 RSS 订阅源（只更新传入字段）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "url": {"type": "string"},
                "tag": {"type": "string"},
                "group_name": {"type": "string"},
                "enabled": {"type": ["boolean", "integer"]},
                "refresh_interval": {"type": "integer", "description": "秒"},
            },
            "required": ["id"],
        },
        "handler": lambda a: rss_update(int(a["id"]), **{k: v for k, v in a.items() if k != "id"}),
    },
    {
        "name": "rss_delete",
        "description": "删除一个 RSS 订阅源。",
        "inputSchema": {"type": "object",
                        "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        "handler": lambda a: rss_delete(a["id"]),
    },
    {
        "name": "rss_recent",
        "description": "查询最近的 RSS 条目。",
        "inputSchema": {"type": "object",
                        "properties": {"limit": {"type": "integer"}}},
        "handler": lambda a: rss_recent(limit=a.get("limit", 20)),
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
    {
        "name": "perf_threads",
        "description": "抓取当前进程各线程正在执行的函数栈快照，用于诊断程序卡死/死锁现场（这是诊断关键工具）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: perf_threads(),
    },
    {
        "name": "perf_stats",
        "description": "查看性能监测模块采集的函数/操作耗时统计（热点定位）。",
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

_TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


# ── MCP JSON-RPC 处理 ─────────────────────────────────────────────────

def _make_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _make_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


_TOOL_ERROR_CODE = -32602
_INTERNAL_ERROR_CODE = -32603


def _call_tool(name, args):
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


# ── stdio 传输 ────────────────────────────────────────────────────────

def run_stdio():
    """MCP stdio 传输：从 stdin 读取 JSON-RPC，写回 → stdout。"""
    import select
    _log("YZplan MCP stdio server 启动")
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle_message(msg)
        except Exception as e:  # noqa: BLE001
            _log("处理消息异常", e)
            resp = _make_error(msg.get("id") if isinstance(msg, dict) else None,
                               _INTERNAL_ERROR_CODE, f"服务内部错误: {e}")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# ── HTTP/SSE 传输 ─────────────────────────────────────────────────────

def _http_handler(env, start_response, session_state):
    from urllib.parse import parse_qs, urlparse
    path = env.get("PATH_INFO", "/")
    method = env.get("REQUEST_METHOD", "GET")
    query = parse_qs(env.get("QUERY_STRING", ""))
    length = int(env.get("CONTENT_LENGTH") or 0)
    body = env["wsgi.input"].read(length) if length else b""

    if path in ("/sse", "/sse?"):
        # Server-Sent Events：为客户端分配 session，发送初始端点
        sid = uuid.uuid4().hex
        url = f"http://{env.get('HTTP_HOST', '127.0.0.1:8765')}/messages?session_id={sid}"
        session_state[sid] = []

        def _events():
            yield f"event: endpoint\ndata: {url}\n\n"
            yield "event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n\n"
            # 长连接保持
            while True:
                yield ": keep-alive\n\n"
                time.sleep(15)

        start_response("200 OK", [("Content-Type", "text/event-stream"),
                                  ("Cache-Control", "no-cache"),
                                  ("Connection", "keep-alive")])
        return _events()

    if path == "/messages" and method == "POST":
        sid = (query.get("session_id") or [""])[0]
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception:
            return _as_json(start_response, {"error": "bad json"}, 400)
        resp = handle_message(msg)
        if resp is not None:
            # 简化：把响应塞进 session 队列（由客户端以 GET /messages 拉取或返回响应）
            session_state.setdefault(sid, []).append(resp)
            return _as_json(start_response, resp)
        return _as_json(start_response, {}, 202)

    if path == "/tools" and method == "GET":
        public_tools = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]
        return _as_json(start_response, {"tools": public_tools})

    if path == "/messages" and method == "GET":
        sid = (query.get("session_id") or [""])[0]
        q = session_state.get(sid, [])
        resp = None
        if q:
            resp = q.pop(0)
        if resp is None:
            resp = {"jsonrpc": "2.0", "result": {}}
        return _as_json(start_response, resp)

    return _as_json(start_response, {"error": "not found"}, 404)


def _as_json(start_response, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start_response(f"{status} OK", [("Content-Type", "application/json"),
                                    ("Content-Length", str(len(body)))])
    return [body]


def run_http(host="127.0.0.1", port=8765):
    from wsgiref.simple_server import make_server
    session_state = {}
    _log(f"YZplan MCP HTTP server 启动于 http://{host}:{port}")
    httpd = make_server(host, int(port), lambda e, s: _http_handler(e, s, session_state))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


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


if __name__ == "__main__":
    main()
