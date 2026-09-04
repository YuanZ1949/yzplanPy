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

def _ensure_todo_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            priority INTEGER DEFAULT 1,
            category TEXT DEFAULT '',
            done INTEGER DEFAULT 0,
            due_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)


def _todo_find(id_):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    _ensure_todo_table(conn)
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
    _ensure_todo_table(conn)
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
    _ensure_todo_table(conn)
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
    _ensure_todo_table(conn)
    conn.execute(f"UPDATE todo_notes SET {', '.join(sets)}, updated_at=? WHERE id=?", params)
    conn.commit()
    conn.close()
    return todo_list(todo_id=id_)


def todo_delete(id_):
    import sqlite3
    conn = sqlite3.connect(_db_path())
    _ensure_todo_table(conn)
    conn.execute("DELETE FROM todo_notes WHERE id=?", (int(id_),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def todo_stats():
    conn = None
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    _ensure_todo_table(conn)
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


# ── RSS 文章级操作 ────────────────────────────────────────────────────

def _rss_items_conn():
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE NOT NULL, title TEXT, link TEXT, published TEXT,
            description TEXT DEFAULT '', image_url TEXT DEFAULT '', read_time INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS item_read(hash TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS read_history(hash TEXT PRIMARY KEY, read_at TEXT);
        CREATE TABLE IF NOT EXISTS favorites(hash TEXT PRIMARY KEY, created_at TEXT, note TEXT DEFAULT '');
    """)
    return conn


def rss_item_list(keyword=None, unread_only=False, favorites_only=False,
                  feed_id=None, tag=None, date_from=None, date_to=None,
                  limit=50, offset=0):
    conn = _rss_items_conn()
    q = ("SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, "
         "CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS is_read, "
         "CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS is_fav "
         "FROM items i "
         "LEFT JOIN item_read r ON i.hash = r.hash "
         "LEFT JOIN favorites f ON i.hash = f.hash")
    conds, params = [], []
    if feed_id is not None:
        q += " JOIN item_feeds if2 ON i.hash = if2.hash"
        conds.append("if2.feed_id = ?")
        params.append(int(feed_id))
    if tag:
        q += " JOIN item_sources is2 ON i.hash = is2.hash"
        conds.append("is2.tag = ?")
        params.append(str(tag))
    if unread_only:
        conds.append("r.hash IS NULL")
    if favorites_only:
        conds.append("f.hash IS NOT NULL")
    if keyword:
        conds.append("(i.title LIKE ? OR i.link LIKE ?)")
        kw = f"%{keyword}%"
        params += [kw, kw]
    if date_from:
        conds.append("i.published >= ?")
        params.append(str(date_from))
    if date_to:
        conds.append("i.published <= ?")
        params.append(str(date_to))
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY i.published DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]
    rows = conn.execute(q, params).fetchall()
    total_q = "SELECT COUNT(*) AS c FROM items i"
    total_params = []
    if feed_id is not None:
        total_q += " JOIN item_feeds if2 ON i.hash = if2.hash"
    if tag:
        total_q += " JOIN item_sources is2 ON i.hash = is2.hash"
    total_conds = []
    if feed_id is not None:
        total_conds.append("if2.feed_id = ?")
        total_params.append(int(feed_id))
    if tag:
        total_conds.append("is2.tag = ?")
        total_params.append(str(tag))
    if unread_only:
        total_conds.append("NOT EXISTS(SELECT 1 FROM item_read r2 WHERE r2.hash=i.hash)")
    if favorites_only:
        total_conds.append("EXISTS(SELECT 1 FROM favorites f2 WHERE f2.hash=i.hash)")
    if keyword:
        total_conds.append("(i.title LIKE ? OR i.link LIKE ?)")
        total_params += [f"%{keyword}%", f"%{keyword}%"]
    if date_from:
        total_conds.append("i.published >= ?")
        total_params.append(str(date_from))
    if date_to:
        total_conds.append("i.published <= ?")
        total_params.append(str(date_to))
    if total_conds:
        total_q += " WHERE " + " AND ".join(total_conds)
    total = conn.execute(total_q, total_params).fetchone()["c"]
    conn.close()
    return {"items": [dict(r) for r in rows], "total": total, "limit": int(limit), "offset": int(offset)}


def rss_item_get(hash_):
    conn = _rss_items_conn()
    row = conn.execute(
        "SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, "
        "CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS is_read, "
        "CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS is_fav "
        "FROM items i "
        "LEFT JOIN item_read r ON i.hash = r.hash "
        "LEFT JOIN favorites f ON i.hash = f.hash "
        "WHERE i.hash = ?", (str(hash_),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 hash={hash_} 的条目")
    result = dict(row)
    cats = conn.execute(
        "SELECT c.id, c.name, c.color FROM categories c "
        "JOIN item_categories ic ON c.id = ic.category_id WHERE ic.hash = ?",
        (str(hash_),)).fetchall()
    result["categories"] = [dict(c) for c in cats]
    tags = conn.execute("SELECT tag FROM item_sources WHERE hash = ?", (str(hash_),)).fetchall()
    result["tags"] = [r["tag"] for r in tags]
    feeds = conn.execute(
        "SELECT f.id, f.name FROM feeds f JOIN item_feeds if2 ON f.id = if2.feed_id "
        "WHERE if2.hash = ?", (str(hash_),)).fetchall()
    result["feeds"] = [dict(f) for f in feeds]
    conn.close()
    return result


def _rss_mark_read(conn, hashes):
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for h in hashes:
        conn.execute("INSERT OR IGNORE INTO item_read(hash) VALUES(?)", (h,))
        conn.execute("INSERT OR REPLACE INTO read_history(hash, read_at) VALUES(?,?)", (h, now))
    conn.commit()


def _rss_mark_unread(conn, hashes):
    for h in hashes:
        conn.execute("DELETE FROM item_read WHERE hash=?", (h,))
    conn.commit()


def rss_mark_read(hashes=None, hash_=None, mark_all=False, tag_filter=None):
    conn = _rss_items_conn()
    if mark_all:
        if tag_filter:
            rows = conn.execute(
                "SELECT i.hash FROM items i JOIN item_sources is2 ON i.hash=is2.hash "
                "WHERE is2.tag=? AND i.hash NOT IN (SELECT hash FROM item_read)",
                (str(tag_filter),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT hash FROM items WHERE hash NOT IN (SELECT hash FROM item_read)").fetchall()
        hashes = [r["hash"] for r in rows]
    elif hash_:
        hashes = [str(hash_)]
    elif not hashes:
        conn.close()
        return {"marked": 0}
    hashes = [str(h) for h in hashes]
    _rss_mark_read(conn, hashes)
    conn.close()
    return {"marked": len(hashes)}


def rss_mark_unread(hashes=None, hash_=None):
    conn = _rss_items_conn()
    h = [str(hash_)] if hash_ else [str(x) for x in (hashes or [])]
    if not h:
        conn.close()
        return {"marked": 0}
    _rss_mark_unread(conn, h)
    conn.close()
    return {"marked": len(h)}


def rss_toggle_favorite(hash_):
    conn = _rss_items_conn()
    row = conn.execute("SELECT hash FROM favorites WHERE hash=?", (str(hash_),)).fetchone()
    if row:
        conn.execute("DELETE FROM favorites WHERE hash=?", (str(hash_),))
        conn.commit()
        conn.close()
        return {"hash": str(hash_), "is_fav": False}
    else:
        conn.execute("INSERT INTO favorites(hash) VALUES(?)", (str(hash_),))
        conn.commit()
        conn.close()
        return {"hash": str(hash_), "is_fav": True}


def rss_batch_delete(hashes):
    if not hashes:
        return {"deleted": 0}
    conn = _rss_items_conn()
    ph = ",".join("?" * len(hashes))
    conn.execute(f"DELETE FROM items WHERE hash IN ({ph})", [str(h) for h in hashes])
    conn.execute(f"DELETE FROM item_read WHERE hash IN ({ph})", [str(h) for h in hashes])
    conn.execute(f"DELETE FROM favorites WHERE hash IN ({ph})", [str(h) for h in hashes])
    conn.execute(f"DELETE FROM read_history WHERE hash IN ({ph})", [str(h) for h in hashes])
    conn.commit()
    conn.close()
    return {"deleted": len(hashes)}


def rss_read_history(limit=50):
    conn = _rss_items_conn()
    rows = conn.execute(
        "SELECT h.hash, h.read_at, i.title, i.link "
        "FROM read_history h LEFT JOIN items i ON h.hash = i.hash "
        "ORDER BY h.read_at DESC LIMIT ?", (int(limit),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── RSS 聚合管理 ──────────────────────────────────────────────────────

def _rss_agg_conn():
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS aggregations(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            agg_type TEXT DEFAULT 'mixed', feed_ids TEXT DEFAULT '[]', tags TEXT DEFAULT '[]',
            kw_required TEXT DEFAULT '[]', kw_optional TEXT DEFAULT '[]', kw_forbidden TEXT DEFAULT '[]',
            sort_order INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
            created_at TEXT, last_refreshed TEXT
        );
        CREATE TABLE IF NOT EXISTS aggregation_items(
            agg_id INTEGER NOT NULL, hash TEXT NOT NULL, added_at TEXT,
            PRIMARY KEY(agg_id, hash)
        );
    """)
    return conn


def rss_agg_list():
    conn = _rss_agg_conn()
    rows = conn.execute("SELECT * FROM aggregations ORDER BY sort_order, created_at").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        cnt = conn.execute("SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (d["id"],)).fetchone()
        d["count"] = cnt["c"] if cnt else 0
        result.append(d)
    conn.close()
    return result


def rss_agg_get(agg_id):
    conn = _rss_agg_conn()
    row = conn.execute("SELECT * FROM aggregations WHERE id=?", (int(agg_id),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 agg_id={agg_id} 的聚合")
    d = dict(row)
    cnt = conn.execute("SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (d["id"],)).fetchone()
    d["count"] = cnt["c"] if cnt else 0
    conn.close()
    return d


def rss_agg_add(name, agg_type="mixed", feed_ids=None, tags=None,
                kw_required=None, kw_optional=None, kw_forbidden=None):
    import json as _json
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    conn = _rss_agg_conn()
    try:
        cur = conn.execute(
            "INSERT INTO aggregations(name, agg_type, feed_ids, tags, kw_required, kw_optional, kw_forbidden) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(name).strip(), str(agg_type),
             _json.dumps(feed_ids or []), _json.dumps(tags or []),
             _json.dumps(kw_required or []), _json.dumps(kw_optional or []),
             _json.dumps(kw_forbidden or [])))
        conn.commit()
        aid = cur.lastrowid
    except Exception as e:
        conn.close()
        raise ValueError(f"新增聚合失败：{e}")
    conn.close()
    return rss_agg_get(aid)


def rss_agg_update(agg_id, **kwargs):
    import json as _json
    conn = _rss_agg_conn()
    row = conn.execute("SELECT id FROM aggregations WHERE id=?", (int(agg_id),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 agg_id={agg_id} 的聚合")
    allowed = ("name", "agg_type", "feed_ids", "tags", "kw_required", "kw_optional",
               "kw_forbidden", "sort_order", "enabled")
    json_fields = ("feed_ids", "tags", "kw_required", "kw_optional", "kw_forbidden")
    sets, params = [], []
    for k in allowed:
        if k in kwargs:
            v = kwargs[k]
            if k in json_fields and isinstance(v, (list, dict)):
                v = _json.dumps(v)
            sets.append(f"{k} = ?")
            params.append(v)
    if sets:
        params.append(int(agg_id))
        conn.execute(f"UPDATE aggregations SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    conn.close()
    return rss_agg_get(agg_id)


def rss_agg_delete(agg_id):
    conn = _rss_agg_conn()
    conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (int(agg_id),))
    conn.execute("DELETE FROM aggregations WHERE id=?", (int(agg_id),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def rss_agg_refresh(agg_id):
    """通过 mcp_inbox 请求 GUI 进程刷新指定聚合。"""
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    payload = {
        "id": uuid.uuid4().hex,
        "command": "refresh_aggregation",
        "agg_id": int(agg_id),
        "title": "聚合刷新",
        "message": f"MCP 请求刷新聚合 #{agg_id}",
        "level": "info",
        "silent": True,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return {"queued": True, "command": "refresh_aggregation", "agg_id": int(agg_id)}


def rss_agg_torrent_groups(agg_id, limit=200):
    """获取磁链聚合的 torrent_hash 分组列表。"""
    conn = _rss_agg_conn()
    rows = conn.execute(
        "SELECT ai.hash, COUNT(*) AS feed_count, "
        "MIN(i.title) AS title FROM aggregation_items ai "
        "JOIN items i ON ai.hash = i.hash "
        "WHERE ai.agg_id = ? GROUP BY ai.hash ORDER BY feed_count DESC LIMIT ?",
        (int(agg_id), int(limit))).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_agg_sidebar():
    """返回侧边栏所需的节点数据与未读计数。"""
    conn = _rss_items_conn()
    feed_rows = conn.execute(
        "SELECT id,name,tag,group_name,enabled FROM feeds ORDER BY sort_order, id").fetchall()
    unread_map = {}
    for r in conn.execute(
        """SELECT f.feed_id, COUNT(DISTINCT i.hash) AS c FROM items i
           JOIN item_feeds f ON i.hash=f.hash LEFT JOIN item_read r ON i.hash=r.hash
           WHERE r.hash IS NULL GROUP BY f.feed_id"""
    ).fetchall():
        unread_map[r["feed_id"]] = r["c"]
    feeds = []
    for f in feed_rows:
        d = dict(f)
        d["unread"] = unread_map.get(f["id"], 0)
        feeds.append(d)
    agg_rows = conn.execute("SELECT * FROM aggregations ORDER BY sort_order, created_at").fetchall()
    agg_count_map = {}
    for r in conn.execute("SELECT agg_id, COUNT(*) AS c FROM aggregation_items GROUP BY agg_id").fetchall():
        agg_count_map[r["agg_id"]] = r["c"]
    aggs = []
    for a in agg_rows:
        d = dict(a)
        d["count"] = agg_count_map.get(d["id"], 0)
        aggs.append(d)
    conn.close()
    return {"feeds": feeds, "aggregations": aggs}


# ── RSS 规则、分类与关键词 ────────────────────────────────────────────

def _rss_rules_conn():
    import sqlite3
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#1a73e8', sort_order INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS keywords(id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT UNIQUE NOT NULL, color TEXT DEFAULT '#ff6b6b', notify INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS filter_rules(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, field TEXT DEFAULT 'title', operator TEXT DEFAULT 'contains', value TEXT NOT NULL, action TEXT DEFAULT 'tag', action_value TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0);
    """)
    return conn


def rss_category_list():
    conn = _rss_rules_conn()
    rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_category_add(name, color="#1a73e8"):
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    conn = _rss_rules_conn()
    try:
        conn.execute("INSERT INTO categories(name, color) VALUES(?,?)", (str(name).strip(), str(color)))
        conn.commit()
    except Exception as e:
        conn.close()
        raise ValueError(f"新增分类失败：{e}")
    row = conn.execute("SELECT * FROM categories WHERE name=?", (str(name).strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_category_update(category_id, name=None, color=None):
    conn = _rss_rules_conn()
    row = conn.execute("SELECT id FROM categories WHERE id=?", (int(category_id),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 category_id={category_id}")
    sets, params = [], []
    if name is not None:
        sets.append("name=?")
        params.append(str(name))
    if color is not None:
        sets.append("color=?")
        params.append(str(color))
    if sets:
        params.append(int(category_id))
        conn.execute(f"UPDATE categories SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (int(category_id),)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_category_delete(category_id):
    conn = _rss_rules_conn()
    conn.execute("DELETE FROM item_categories WHERE category_id=?", (int(category_id),))
    conn.execute("DELETE FROM categories WHERE id=?", (int(category_id),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def rss_keyword_list():
    conn = _rss_rules_conn()
    rows = conn.execute("SELECT * FROM keywords ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_keyword_add(keyword, color="#ff6b6b", notify=True):
    if not keyword or not str(keyword).strip():
        raise ValueError("keyword 不能为空")
    conn = _rss_rules_conn()
    try:
        conn.execute("INSERT INTO keywords(keyword, color, notify) VALUES(?,?,?)",
                     (str(keyword).strip(), str(color), int(bool(notify))))
        conn.commit()
    except Exception as e:
        conn.close()
        raise ValueError(f"新增关键词失败：{e}")
    row = conn.execute("SELECT * FROM keywords WHERE keyword=?", (str(keyword).strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_keyword_delete(keyword_id):
    conn = _rss_rules_conn()
    conn.execute("DELETE FROM keywords WHERE id=?", (int(keyword_id),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def rss_filter_list():
    conn = _rss_rules_conn()
    rows = conn.execute("SELECT * FROM filter_rules ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_filter_add(name, field="title", operator="contains", value="", action="tag", action_value="", enabled=True):
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    conn = _rss_rules_conn()
    cur = conn.execute(
        "INSERT INTO filter_rules(name, field, operator, value, action, action_value, enabled) VALUES(?,?,?,?,?,?,?)",
        (str(name).strip(), str(field), str(operator), str(value), str(action), str(action_value), int(bool(enabled))))
    conn.commit()
    rid = cur.lastrowid
    row = conn.execute("SELECT * FROM filter_rules WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_filter_update(rule_id, enabled=None, name=None, field=None, operator=None,
                      value=None, action=None, action_value=None):
    conn = _rss_rules_conn()
    row = conn.execute("SELECT id FROM filter_rules WHERE id=?", (int(rule_id),)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"找不到 rule_id={rule_id}")
    fields = {"name": name, "field": field, "operator": operator, "value": value,
              "action": action, "action_value": action_value, "enabled": enabled}
    sets, params = [], []
    for k, v in fields.items():
        if v is not None:
            sets.append(f"{k}=?")
            params.append(int(v) if k == "enabled" else v)
    if sets:
        params.append(int(rule_id))
        conn.execute(f"UPDATE filter_rules SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    row = conn.execute("SELECT * FROM filter_rules WHERE id=?", (int(rule_id),)).fetchone()
    conn.close()
    return dict(row) if row else None


def rss_filter_delete(rule_id):
    conn = _rss_rules_conn()
    conn.execute("DELETE FROM filter_rules WHERE id=?", (int(rule_id),))
    conn.commit()
    conn.close()
    return {"deleted": True}


def rss_cleanup(days=30):
    conn = _rss_items_conn()
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
    cur = conn.execute(
        "DELETE FROM items WHERE hash NOT IN (SELECT hash FROM favorites) AND published < ?", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return {"deleted": deleted, "cutoff": cutoff}


# ── 应用配置与模块管理 ────────────────────────────────────────────────

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


# ── RSS 高级功能 ──────────────────────────────────────────────────────

def rss_opml_export():
    """导出所有订阅源为 OPML XML 字符串。"""
    conn = _rss_store()
    rows = conn.execute("SELECT name, url, tag, group_name FROM feeds ORDER BY sort_order, id").fetchall()
    conn.close()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<opml version="2.0"><head><title>YZplan RSS</title></head><body>']
    for r in rows:
        tag = r["tag"] or r["group_name"] or "未分组"
        lines.append(f'  <outline text="{tag}">')
        lines.append(f'    <outline type="rss" text="{r["name"]}" title="{r["name"]}" xmlUrl="{r["url"]}" htmlUrl="{r["url"]}"/>')
        lines.append('  </outline>')
    lines.append('</body></opml>')
    return {"opml": "\n".join(lines), "count": len(rows)}


def rss_opml_import(opml_content):
    """从 OPML XML 导入订阅源。返回导入数量和失败列表。"""
    import re
    if not opml_content:
        raise ValueError("opml_content 不能为空")
    entries = re.findall(
        r'<outline[^>]*type="rss"[^>]*text="([^"]*)"[^>]*xmlUrl="([^"]*)"[^>]*/>', opml_content)
    if not entries:
        entries = re.findall(
            r'<outline[^>]*xmlUrl="([^"]*)"[^>]*text="([^"]*)"[^>]*/>', opml_content)
        entries = [(t, u) for u, t in entries]
    imported, failed = 0, []
    for name, url in entries:
        try:
            rss_add(name, url)
            imported += 1
        except Exception as e:
            failed.append({"name": name, "url": url, "error": str(e)})
    return {"imported": imported, "failed": failed, "total_found": len(entries)}


def rss_discover(url):
    """从 URL 自动发现 RSS/Atom 订阅源。"""
    conn = _rss_store()
    try:
        import sqlite3 as _s3
        conn2 = sqlite3.connect(_db_path())
        conn2.row_factory = sqlite3.Row
        conn2.executescript("""
            CREATE TABLE IF NOT EXISTS feeds(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, url TEXT NOT NULL, tag TEXT, enabled INTEGER DEFAULT 1, group_name TEXT DEFAULT '', refresh_interval INTEGER DEFAULT 1800, last_refresh TEXT, custom_headers TEXT DEFAULT '{}', etag TEXT DEFAULT '', last_modified TEXT DEFAULT '', last_error TEXT DEFAULT '', error_count INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0);
        """)
        conn2.close()
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(str(url), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        import re
        feeds = re.findall(r'<link[^>]*type="application/(?:rss\+xml|atom\+xml)"[^>]*href="([^"]*)"[^>]*>', html)
        if not feeds:
            feeds = re.findall(r'href="([^"]*)"[^>]*type="application/(?:rss\+xml|atom\+xml)"', html)
        results = []
        for f in feeds:
            if f.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(str(url))
                f = f"{parsed.scheme}://{parsed.netloc}{f}"
            results.append({"url": f})
        return {"discovered": results, "source_url": str(url)}
    except Exception as e:
        return {"discovered": [], "source_url": str(url), "error": str(e)}


def rss_refresh():
    """请求 GUI 刷新全部 RSS 订阅源（通过 mcp_inbox IPC）。"""
    return _mcp_inbox_command("refresh_feeds", {"title": "RSS 刷新", "message": "MCP 请求刷新全部订阅源"})


def rss_stats():
    """查看各订阅源的条目统计。"""
    conn = _rss_items_conn()
    rows = conn.execute(
        "SELECT f.id, f.name, COUNT(i.hash) AS total, "
        "SUM(CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END) AS read_count "
        "FROM feeds f LEFT JOIN item_feeds if2 ON f.id=if2.feed_id "
        "LEFT JOIN items i ON if2.hash=i.hash "
        "LEFT JOIN item_read r ON i.hash=r.hash "
        "GROUP BY f.id ORDER BY f.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rss_tags():
    """列出所有 RSS 标签（来源标签）。"""
    conn = _rss_items_conn()
    rows = conn.execute("SELECT DISTINCT tag FROM item_sources WHERE tag != '' ORDER BY tag").fetchall()
    groups = conn.execute("SELECT DISTINCT group_name FROM feeds WHERE group_name != '' ORDER BY group_name").fetchall()
    conn.close()
    return {"tags": [r["tag"] for r in rows], "groups": [r["group_name"] for r in groups]}


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
    import subprocess
    try:
        cmd = f'netsh advfirewall firewall add rule name="YZplan_Block_{host_or_path}" dir=out action=block remoteip="{host_or_path}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10,
                                creationflags=0x08000000)
        return {"success": "OK" in result.stdout, "output": result.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def webview_unblock(name):
    """删除指定的 WebView2 防火墙拦截规则。"""
    import subprocess
    try:
        cmd = f'netsh advfirewall firewall delete rule name="YZplan_Block_{name}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10,
                                creationflags=0x08000000)
        return {"success": "OK" in result.stdout, "output": result.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def webview_kill():
    """终止所有 WebView2 进程（通过 mcp_inbox IPC 让 GUI 执行，以确保权限正确）。"""
    return _mcp_inbox_command("webview_kill", {"title": "WebView2", "message": "MCP 请求终止 WebView2 进程"})


def webview_scan():
    """请求 GUI 扫描 WebView2 程序列表（通过 mcp_inbox IPC）。"""
    return _mcp_inbox_command("scan_webview", {"title": "WebView2 扫描", "message": "MCP 请求扫描 WebView2"})


def webview_rules():
    """获取当前所有 YZplan 相关的防火墙规则。"""
    import subprocess
    try:
        result = subprocess.run(
            'netsh advfirewall firewall show rule name=all dir=out | findstr /I "YZplan_Block_"',
            shell=True, capture_output=True, text=True, timeout=10,
            creationflags=0x08000000)
        rules = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        return {"rules": rules, "count": len(rules)}
    except Exception as e:
        return {"rules": [], "count": 0, "error": str(e)}


# ── GUI 导航与系统工具 ────────────────────────────────────────────────

def gui_show_window():
    """请求 GUI 显示主窗口。"""
    return _mcp_inbox_command("show_window", {"title": "YZplan", "message": "MCP 请求显示窗口", "silent": True})


def gui_navigate(module_id):
    """请求 GUI 跳转到指定模块页面。"""
    return _mcp_inbox_command("navigate_module", {
        "module_id": str(module_id), "title": "YZplan", "message": f"跳转到 {module_id}", "silent": True})


def gui_export_logs():
    """请求 GUI 导出日志到文件（通过 mcp_inbox IPC）。"""
    return _mcp_inbox_command("export_logs", {"title": "日志导出", "message": "MCP 请求导出日志"})


def gui_quit():
    """请求 GUI 退出程序。"""
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
        "name": "rss_item_list",
        "description": "高级查询 RSS 文章条目：支持关键词搜索、未读/收藏筛选、按订阅源/标签/日期范围过滤，带分页。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "按标题/链接关键词搜索"},
                "unread_only": {"type": "boolean", "description": "仅未读条目"},
                "favorites_only": {"type": "boolean", "description": "仅收藏条目"},
                "feed_id": {"type": "integer", "description": "按订阅源 ID 筛选"},
                "tag": {"type": "string", "description": "按标签筛选"},
                "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "截止日期 YYYY-MM-DD"},
                "limit": {"type": "integer", "description": "每页条数（默认 50）"},
                "offset": {"type": "integer", "description": "偏移量（默认 0）"},
            },
        },
        "handler": lambda a: rss_item_list(
            keyword=a.get("keyword"), unread_only=a.get("unread_only", False),
            favorites_only=a.get("favorites_only", False),
            feed_id=a.get("feed_id"), tag=a.get("tag"),
            date_from=a.get("date_from"), date_to=a.get("date_to"),
            limit=a.get("limit", 50), offset=a.get("offset", 0)),
    },
    {
        "name": "rss_item_get",
        "description": "获取单条 RSS 文章详情（含分类、标签、来源订阅源、已读/收藏状态）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "必填，条目 hash"},
            },
            "required": ["hash"],
        },
        "handler": lambda a: rss_item_get(a["hash"]),
    },
    {
        "name": "rss_mark_read",
        "description": "标记 RSS 文章为已读。支持单条(hash)、批量(hashes)、全部已读(mark_all)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "单条 hash"},
                "hashes": {"type": "array", "items": {"type": "string"}, "description": "批量 hash 列表"},
                "mark_all": {"type": "boolean", "description": "标记全部为已读"},
                "tag_filter": {"type": "string", "description": "配合 mark_all 使用，仅标记指定标签的条目"},
            },
        },
        "handler": lambda a: rss_mark_read(
            hashes=a.get("hashes"), hash_=a.get("hash"),
            mark_all=a.get("mark_all", False), tag_filter=a.get("tag_filter")),
    },
    {
        "name": "rss_mark_unread",
        "description": "标记 RSS 文章为未读。支持单条(hash)或批量(hashes)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "单条 hash"},
                "hashes": {"type": "array", "items": {"type": "string"}, "description": "批量 hash 列表"},
            },
        },
        "handler": lambda a: rss_mark_unread(hashes=a.get("hashes"), hash_=a.get("hash")),
    },
    {
        "name": "rss_toggle_favorite",
        "description": "切换 RSS 文章的收藏状态（已收藏→取消，未收藏→收藏）。返回新状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "必填，条目 hash"},
            },
            "required": ["hash"],
        },
        "handler": lambda a: rss_toggle_favorite(a["hash"]),
    },
    {
        "name": "rss_batch_delete",
        "description": "批量删除 RSS 文章条目（同时清除已读/收藏记录）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hashes": {"type": "array", "items": {"type": "string"}, "description": "必填，hash 列表"},
            },
            "required": ["hashes"],
        },
        "handler": lambda a: rss_batch_delete(a["hashes"]),
    },
    {
        "name": "rss_read_history",
        "description": "查询 RSS 文章的阅读历史记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "条数上限（默认 50）"},
            },
        },
        "handler": lambda a: rss_read_history(limit=a.get("limit", 50)),
    },
    {
        "name": "rss_agg_list",
        "description": "列出所有 RSS 聚合（含成员数）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_agg_list(),
    },
    {
        "name": "rss_agg_get",
        "description": "获取指定聚合的详情。",
        "inputSchema": {
            "type": "object",
            "properties": {"agg_id": {"type": "integer", "description": "聚合 ID"}},
            "required": ["agg_id"],
        },
        "handler": lambda a: rss_agg_get(a["agg_id"]),
    },
    {
        "name": "rss_agg_add",
        "description": "新建 RSS 聚合。支持混合(mixed)、关键词(keyword)、磁链(torrent)三种类型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "必填，聚合名称"},
                "agg_type": {"type": "string", "description": "聚合类型：mixed/keyword/torrent"},
                "feed_ids": {"type": "array", "items": {"type": "integer"}, "description": "成员订阅源 ID 列表"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "成员标签列表"},
                "kw_required": {"type": "array", "items": {"type": "string"}, "description": "关键词-必须包含"},
                "kw_optional": {"type": "array", "items": {"type": "string"}, "description": "关键词-可选包含"},
                "kw_forbidden": {"type": "array", "items": {"type": "string"}, "description": "关键词-排除"},
            },
            "required": ["name"],
        },
        "handler": lambda a: rss_agg_add(
            a["name"], agg_type=a.get("agg_type", "mixed"),
            feed_ids=a.get("feed_ids"), tags=a.get("tags"),
            kw_required=a.get("kw_required"), kw_optional=a.get("kw_optional"),
            kw_forbidden=a.get("kw_forbidden")),
    },
    {
        "name": "rss_agg_update",
        "description": "更新 RSS 聚合（只更新传入字段）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agg_id": {"type": "integer", "description": "聚合 ID"},
                "name": {"type": "string"},
                "agg_type": {"type": "string"},
                "feed_ids": {"type": "array", "items": {"type": "integer"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "kw_required": {"type": "array", "items": {"type": "string"}},
                "kw_optional": {"type": "array", "items": {"type": "string"}},
                "kw_forbidden": {"type": "array", "items": {"type": "string"}},
                "sort_order": {"type": "integer"},
                "enabled": {"type": ["boolean", "integer"]},
            },
            "required": ["agg_id"],
        },
        "handler": lambda a: rss_agg_update(int(a["agg_id"]), **{k: v for k, v in a.items() if k != "agg_id"}),
    },
    {
        "name": "rss_agg_delete",
        "description": "删除 RSS 聚合及其成员关系。",
        "inputSchema": {
            "type": "object",
            "properties": {"agg_id": {"type": "integer", "description": "聚合 ID"}},
            "required": ["agg_id"],
        },
        "handler": lambda a: rss_agg_delete(a["agg_id"]),
    },
    {
        "name": "rss_agg_refresh",
        "description": "请求 GUI 刷新指定聚合（通过 mcp_inbox IPC，需要 GUI 正在运行）。",
        "inputSchema": {
            "type": "object",
            "properties": {"agg_id": {"type": "integer", "description": "聚合 ID"}},
            "required": ["agg_id"],
        },
        "handler": lambda a: rss_agg_refresh(a["agg_id"]),
    },
    {
        "name": "rss_agg_torrent_groups",
        "description": "获取磁链聚合的 torrent_hash 分组列表（每个 hash 的来源数和标题）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agg_id": {"type": "integer", "description": "聚合 ID"},
                "limit": {"type": "integer", "description": "返回条数上限"},
            },
            "required": ["agg_id"],
        },
        "handler": lambda a: rss_agg_torrent_groups(a["agg_id"], limit=a.get("limit", 200)),
    },
    {
        "name": "rss_agg_sidebar",
        "description": "获取 RSS 侧边栏数据（所有订阅源和聚合的摘要信息与未读计数）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_agg_sidebar(),
    },
    {
        "name": "rss_category_list",
        "description": "列出所有 RSS 文章分类。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_category_list(),
    },
    {
        "name": "rss_category_add",
        "description": "新增 RSS 文章分类。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "必填，分类名称"},
                "color": {"type": "string", "description": "颜色（默认 #1a73e8）"},
            },
            "required": ["name"],
        },
        "handler": lambda a: rss_category_add(a["name"], color=a.get("color", "#1a73e8")),
    },
    {
        "name": "rss_category_update",
        "description": "更新 RSS 文章分类。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category_id": {"type": "integer", "description": "分类 ID"},
                "name": {"type": "string"},
                "color": {"type": "string"},
            },
            "required": ["category_id"],
        },
        "handler": lambda a: rss_category_update(int(a["category_id"]), name=a.get("name"), color=a.get("color")),
    },
    {
        "name": "rss_category_delete",
        "description": "删除 RSS 文章分类。",
        "inputSchema": {
            "type": "object",
            "properties": {"category_id": {"type": "integer", "description": "分类 ID"}},
            "required": ["category_id"],
        },
        "handler": lambda a: rss_category_delete(a["category_id"]),
    },
    {
        "name": "rss_keyword_list",
        "description": "列出所有 RSS 关键词监控规则。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_keyword_list(),
    },
    {
        "name": "rss_keyword_add",
        "description": "新增 RSS 关键词监控（匹配时高亮并可选通知）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "必填，关键词"},
                "color": {"type": "string", "description": "高亮颜色（默认 #ff6b6b）"},
                "notify": {"type": "boolean", "description": "是否弹出通知（默认 true）"},
            },
            "required": ["keyword"],
        },
        "handler": lambda a: rss_keyword_add(a["keyword"], color=a.get("color", "#ff6b6b"), notify=a.get("notify", True)),
    },
    {
        "name": "rss_keyword_delete",
        "description": "删除 RSS 关键词监控。",
        "inputSchema": {
            "type": "object",
            "properties": {"keyword_id": {"type": "integer", "description": "关键词 ID"}},
            "required": ["keyword_id"],
        },
        "handler": lambda a: rss_keyword_delete(a["keyword_id"]),
    },
    {
        "name": "rss_filter_list",
        "description": "列出所有 RSS 过滤规则。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_filter_list(),
    },
    {
        "name": "rss_filter_add",
        "description": "新增 RSS 过滤规则（可按标题/描述等字段，匹配后自动打标签/删除等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "必填，规则名称"},
                "field": {"type": "string", "description": "匹配字段：title/description/link"},
                "operator": {"type": "string", "description": "匹配方式：contains/equals/not_contains/regex"},
                "value": {"type": "string", "description": "匹配值"},
                "action": {"type": "string", "description": "匹配后动作：tag/delete/hide"},
                "action_value": {"type": "string", "description": "动作参数（如 tag 名）"},
                "enabled": {"type": "boolean", "description": "是否启用"},
            },
            "required": ["name", "value"],
        },
        "handler": lambda a: rss_filter_add(
            a["name"], field=a.get("field", "title"), operator=a.get("operator", "contains"),
            value=a.get("value", ""), action=a.get("action", "tag"),
            action_value=a.get("action_value", ""), enabled=a.get("enabled", True)),
    },
    {
        "name": "rss_filter_update",
        "description": "更新 RSS 过滤规则。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer", "description": "规则 ID"},
                "name": {"type": "string"},
                "field": {"type": "string"},
                "operator": {"type": "string"},
                "value": {"type": "string"},
                "action": {"type": "string"},
                "action_value": {"type": "string"},
                "enabled": {"type": ["boolean", "integer"]},
            },
            "required": ["rule_id"],
        },
        "handler": lambda a: rss_filter_update(
            int(a["rule_id"]), name=a.get("name"), field=a.get("field"),
            operator=a.get("operator"), value=a.get("value"),
            action=a.get("action"), action_value=a.get("action_value"),
            enabled=a.get("enabled")),
    },
    {
        "name": "rss_filter_delete",
        "description": "删除 RSS 过滤规则。",
        "inputSchema": {
            "type": "object",
            "properties": {"rule_id": {"type": "integer", "description": "规则 ID"}},
            "required": ["rule_id"],
        },
        "handler": lambda a: rss_filter_delete(a["rule_id"]),
    },
    {
        "name": "rss_cleanup",
        "description": "清理过期 RSS 文章数据（收藏的不会被删除）。默认清理 30 天前的数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "保留天数（默认 30）"},
            },
        },
        "handler": lambda a: rss_cleanup(days=a.get("days", 30)),
    },
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
    {
        "name": "rss_opml_export",
        "description": "导出所有 RSS 订阅源为 OPML XML 格式。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_opml_export(),
    },
    {
        "name": "rss_opml_import",
        "description": "从 OPML XML 导入 RSS 订阅源。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opml_content": {"type": "string", "description": "必填，OPML XML 内容"},
            },
            "required": ["opml_content"],
        },
        "handler": lambda a: rss_opml_import(a["opml_content"]),
    },
    {
        "name": "rss_discover",
        "description": "从 URL 自动发现 RSS/Atom 订阅源链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "必填，网页 URL"},
            },
            "required": ["url"],
        },
        "handler": lambda a: rss_discover(a["url"]),
    },
    {
        "name": "rss_refresh",
        "description": "请求 GUI 刷新全部 RSS 订阅源（通过 mcp_inbox IPC，需要 GUI 正在运行）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_refresh(),
    },
    {
        "name": "rss_stats",
        "description": "查看各 RSS 订阅源的条目统计（总数、已读数）。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_stats(),
    },
    {
        "name": "rss_tags",
        "description": "列出所有 RSS 来源标签和订阅源分组。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: rss_tags(),
    },
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
