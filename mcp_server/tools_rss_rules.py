"""MCP 工具切片：RSS 分类/关键词/过滤规则与数据清理 (rss_category_*/rss_keyword_*/rss_filter_*/rss_cleanup)。

handler 保持函数内 lazy import 数据层（modules.rss_store.RssStore）。
"""


# ── RSS 规则、分类与关键词 ────────────────────────────────────────────

def rss_category_list():
    from .tools_rss_feeds import _rss_store
    rows = [dict(r) for r in _rss_store().get_categories()]
    rows.sort(key=lambda d: (d.get("sort_order", 0), d["id"]))
    return rows


def rss_category_add(name, color="#1a73e8"):
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    nm = str(name).strip()
    if any(c["name"] == nm for c in store.get_categories()):
        raise ValueError("新增分类失败：UNIQUE constraint failed: categories.name")
    try:
        store.add_category(nm, str(color))
    except Exception as e:
        raise ValueError(f"新增分类失败：{e}")
    return next((c for c in store.get_categories() if c["name"] == nm), None)


def rss_category_update(category_id, name=None, color=None):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    cid = int(category_id)
    if not any(c["id"] == cid for c in store.get_categories()):
        raise ValueError(f"找不到 category_id={category_id}")
    store.update_category(cid, name=str(name) if name is not None else None,
                          color=str(color) if color is not None else None)
    return next((c for c in store.get_categories() if c["id"] == cid), None)


def rss_category_delete(category_id):
    from .tools_rss_feeds import _rss_store
    _rss_store().remove_category(int(category_id))
    return {"deleted": True}


def rss_keyword_list():
    from .tools_rss_feeds import _rss_store
    rows = [dict(r) for r in _rss_store().get_keywords()]
    rows.sort(key=lambda d: d["id"])
    return rows


def rss_keyword_add(keyword, color="#ff6b6b", notify=True):
    if not keyword or not str(keyword).strip():
        raise ValueError("keyword 不能为空")
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    kw = str(keyword).strip()
    if any(k["keyword"] == kw for k in store.get_keywords()):
        raise ValueError("新增关键词失败：UNIQUE constraint failed: keywords.keyword")
    store.add_keyword(kw, str(color), int(bool(notify)))
    return next((k for k in store.get_keywords() if k["keyword"] == kw), None)


def rss_keyword_delete(keyword_id):
    from .tools_rss_feeds import _rss_store
    _rss_store().remove_keyword(int(keyword_id))
    return {"deleted": True}


def rss_filter_list():
    from .tools_rss_feeds import _rss_store
    return _rss_store().get_filter_rules()


def rss_filter_add(name, field="title", operator="contains", value="", action="tag", action_value="", enabled=True):
    if not name or not str(name).strip():
        raise ValueError("name 不能为空")
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    rid = store.add_filter_rule_full(str(name).strip(), str(field), str(operator), str(value),
                                     str(action), str(action_value), enabled)
    return next((r for r in store.get_filter_rules() if r["id"] == rid), None)


def rss_filter_update(rule_id, enabled=None, name=None, field=None, operator=None,
                      value=None, action=None, action_value=None):
    from .tools_rss_feeds import _rss_store
    store = _rss_store()
    rid = int(rule_id)
    if not any(r["id"] == rid for r in store.get_filter_rules()):
        raise ValueError(f"找不到 rule_id={rule_id}")
    store.update_filter_rule_full(rid, name=name, field=field, operator=operator, value=value,
                                  action=action, action_value=action_value, enabled=enabled)
    return next((r for r in store.get_filter_rules() if r["id"] == rid), None)


def rss_filter_delete(rule_id):
    from .tools_rss_feeds import _rss_store
    _rss_store().remove_filter_rule(int(rule_id))
    return {"deleted": True}


def rss_cleanup(days=30):
    from .tools_rss_feeds import _rss_store
    deleted, cutoff = _rss_store().cleanup_old_by_date(int(days))
    return {"deleted": deleted, "cutoff": cutoff}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
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
]