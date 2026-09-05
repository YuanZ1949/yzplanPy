"""MCP 工具切片：RSS 订阅源管理 (rss_* feeds)。

handler 保持函数内 lazy import 数据层（modules.rss_store.RssStore）。
tools_rss_items / tools_rss_agg / tools_rss_rules / tools_rss_advanced
通过 `from .tools_rss_feeds import _rss_store` 复用数据访问辅助。
"""

import os


# ── 数据访问层（直接读写 SQLite，不依赖 GUI）───────────────────────────

def _db_path():
    from core.constants import DB_PATH, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    return DB_PATH


def _dbs():
    from core.constants import DB_PATH, DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)


# ── RSS 管理 ──────────────────────────────────────────────────────────

def _rss_store():
    from modules.rss_store import RssStore
    return RssStore(_db_path())


def rss_list():
    store = _rss_store()
    feeds = store.list_feeds()
    for f in feeds:
        f.pop("tags", None)
    feeds.sort(key=lambda f: (f.get("sort_order", 0), f["id"]))
    return feeds


def rss_add(name, url, tag="", group_name="", enabled=True):
    store = _rss_store()
    nm, ur = str(name).strip(), str(url).strip()
    if any(f["name"] == nm for f in store.list_feeds()):
        raise ValueError("新增 RSS 失败（可能名称重复）")
    store.add_feed(nm, ur, tag, group_name=group_name)
    fid = next(f["id"] for f in store.list_feeds() if f["name"] == nm)
    if not enabled:
        store.update_feed(fid, enabled=0)
    return rss_list_by_id(fid)


def rss_list_by_id(fid):
    store = _rss_store()
    d = store.get_feed_by_id(int(fid))
    if d:
        d.pop("tags", None)
    return d


def rss_update(fid, **_kwargs):
    store = _rss_store()
    fid = int(fid)
    if store.get_feed_by_id(fid) is None:
        raise ValueError(f"找不到 id={fid} 的 RSS 源")
    allowed = ("name", "url", "tag", "group_name", "enabled", "refresh_interval")
    sets = {k: _kwargs[k] for k in allowed if k in _kwargs}
    if sets:
        store.update_feed(fid, **sets)
    return rss_list_by_id(fid)


def rss_delete(fid):
    store = _rss_store()
    store.remove_feed(int(fid))
    return {"deleted": True}


def rss_recent(limit=20):
    import sqlite3
    store = _rss_store()
    try:
        rows = store.recent(limit=int(limit))
    except sqlite3.OperationalError:
        rows = []
    return [{"hash": r["hash"], "title": r["title"], "link": r["link"], "published": r["published"]} for r in rows]


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
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
]