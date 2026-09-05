"""MCP 工具切片：RSS 聚合管理 (rss_agg_*)。

handler 保持函数内 lazy import 数据层（modules.rss_store.RssStore）。
rss_agg_refresh 通过 mcp_inbox IPC 请求 GUI 刷新，与旧实现一致。
"""

import json
import os
import time
import uuid


# ── RSS 聚合管理 ──────────────────────────────────────────────────────

def rss_agg_list():
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    result = []
    for d in store.list_aggregations():
        d = dict(d)
        d["count"] = store.get_aggregation_item_count(d["id"])
        result.append(d)
    return result


def rss_agg_get(agg_id):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    d = store.get_aggregation(int(agg_id))
    if not d:
        raise ValueError(f"找不到 agg_id={agg_id} 的聚合")
    d = dict(d)
    d["count"] = store.get_aggregation_item_count(d["id"])
    return d


def rss_agg_add(name, agg_type="mixed", feed_ids=None, tags=None,
                kw_required=None, kw_optional=None, kw_forbidden=None):
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    try:
        aid = store.add_aggregation(str(name).strip(), str(agg_type),
                                    feed_ids, tags, kw_required, kw_optional, kw_forbidden)
    except Exception as e:
        raise ValueError(f"新增聚合失败：{e}")
    return rss_agg_get(aid)


def rss_agg_update(agg_id, **kwargs):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    if not store.get_aggregation(int(agg_id)):
        raise ValueError(f"找不到 agg_id={agg_id} 的聚合")
    allowed = ("name", "agg_type", "feed_ids", "tags", "kw_required", "kw_optional",
               "kw_forbidden", "sort_order", "enabled")
    sets = {k: kwargs[k] for k in allowed if k in kwargs}
    if sets:
        store.update_aggregation(int(agg_id), **sets)
    return rss_agg_get(agg_id)


def rss_agg_delete(agg_id):
    from .tools_rss_feeds import _rss_store
    _rss_store().remove_aggregation(int(agg_id))
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
    from .tools_rss_feeds import _rss_store
    return _rss_store().get_torrent_groups(int(agg_id), int(limit))


def rss_agg_sidebar():
    """返回侧边栏所需的节点数据与未读计数。"""
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    sidebar = store.list_sidebar()
    so_map = {f["id"]: f.get("sort_order", 0) for f in store.list_feeds()}
    feeds = []
    for f in sidebar["feeds"]:
        feeds.append({
            "id": f["id"], "name": f["name"], "tag": f["tag"],
            "group_name": f["group_name"], "enabled": f["enabled"], "unread": f["unread"],
        })
    feeds.sort(key=lambda d: (so_map.get(d["id"], 0), d["id"]))
    aggs = [{k: v for k, v in a.items() if k != "unread"} for a in sidebar["aggregations"]]
    return {"feeds": feeds, "aggregations": aggs}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
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
]