"""MCP 工具切片：RSS 文章级操作 (rss_item_*/rss_mark_*/rss_*_favorite 等)。

handler 保持函数内 lazy import 数据层（modules.rss_store.RssStore）。
"""


# ── RSS 文章级操作 ────────────────────────────────────────────────────

def rss_item_list(keyword=None, unread_only=False, favorites_only=False,
                  feed_id=None, tag=None, date_from=None, date_to=None,
                  limit=50, offset=0):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    date_range = None
    if date_from or date_to:
        date_range = ("range", date_from or "1970-01-01", date_to or "2999-12-31")
    rows = store.recent(
        limit=10 ** 6,
        favorites_only=favorites_only,
        unread_only=unread_only,
        feed_ids=[int(feed_id)] if feed_id is not None else None,
        tags=[str(tag)] if tag else None,
        keyword=keyword,
        date_range=date_range,
    )
    items = [{
        "hash": r["hash"], "title": r["title"], "link": r["link"],
        "published": r["published"], "description": r["description"],
        "image_url": r["image_url"],
        "is_read": r["read"], "is_fav": r["favorite"],
    } for r in rows]
    total = len(items)
    window = items[offset:offset + int(limit)]
    return {"items": window, "total": total, "limit": int(limit), "offset": int(offset)}


def rss_item_get(hash_):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    row = store.get_item(str(hash_))
    if not row:
        raise ValueError(f"找不到 hash={hash_} 的条目")
    return {
        "hash": row["hash"], "title": row["title"], "link": row["link"],
        "published": row["published"], "description": row["description"],
        "image_url": row["image_url"],
        "is_read": row["read"], "is_fav": row["favorite"],
        "categories": store.get_item_categories(str(hash_)),
        "tags": [t for t in (row["tags"] or "").split(" | ") if t],
        "feeds": store.get_item_feeds(str(hash_)),
    }


def rss_mark_read(hashes=None, hash_=None, mark_all=False, tag_filter=None):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    if mark_all:
        if tag_filter:
            items = store.recent(limit=10 ** 6, unread_only=True, tags=[str(tag_filter)])
        else:
            items = store.recent(limit=10 ** 6, unread_only=True)
        hashes = [it["hash"] for it in items]
        store.batch_mark_read(hashes)
    elif hash_:
        hashes = [str(hash_)]
    elif not hashes:
        return {"marked": 0}
    hashes = [str(h) for h in hashes]
    store.batch_mark_read(hashes)
    return {"marked": len(hashes)}


def rss_mark_unread(hashes=None, hash_=None):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    h = [str(hash_)] if hash_ else [str(x) for x in (hashes or [])]
    if not h:
        return {"marked": 0}
    store.batch_mark_unread(h)
    return {"marked": len(h)}


def rss_toggle_favorite(hash_):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    return {"hash": str(hash_), "is_fav": store.toggle_favorite(str(hash_))}


def rss_batch_delete(hashes):
    if not hashes:
        return {"deleted": 0}
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    store.batch_delete([str(h) for h in hashes])
    return {"deleted": len(hashes)}


def rss_read_history(limit=50):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    rows = store.get_read_history(limit=int(limit))
    return [{"hash": r["hash"], "read_at": r["read_at"], "title": r["title"], "link": r["link"]} for r in rows]


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
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
]