"""MCP 工具切片：RSS 分类/关键词/过滤规则与数据清理 (rss_category_*/rss_keyword_*/rss_filter_*/rss_cleanup)。

TOOLS 定义聚合于此；handler 实现在 rss_rules_impl.py（函数内 lazy import 数据层）。
"""


from .rss_rules_impl import (
    rss_category_add,
    rss_category_delete,
    rss_category_list,
    rss_category_update,
    rss_cleanup,
    rss_filter_add,
    rss_filter_delete,
    rss_filter_list,
    rss_filter_update,
    rss_keyword_add,
    rss_keyword_delete,
    rss_keyword_list,
)


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