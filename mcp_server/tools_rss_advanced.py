"""MCP 工具切片：RSS 高级功能 (rss_opml_*/rss_discover/rss_refresh/rss_preview/rss_stats/rss_tags)。

handler 保持函数内 lazy import 数据层与共享辅助：
rss_opml_import 复用 tools_rss_feeds.rss_add；rss_refresh/rss_preview 经
mcp_inbox IPC 请求 GUI（tools_system_config_gui._mcp_inbox_command）。
"""


# ── RSS 高级功能 ──────────────────────────────────────────────────────

def rss_opml_export():
    """导出所有订阅源为 OPML XML 字符串。"""
    from .tools_rss_feeds import _rss_store
    rows = [dict(r) for r in _rss_store().list_feeds()]
    rows.sort(key=lambda f: (f.get("sort_order", 0), f["id"]))
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
    from .tools_rss_feeds import rss_add
    for name, url in entries:
        try:
            rss_add(name, url)
            imported += 1
        except Exception as e:
            failed.append({"name": name, "url": url, "error": str(e)})
    return {"imported": imported, "failed": failed, "total_found": len(entries)}


def rss_discover(url):
    """从 URL 自动发现 RSS/Atom 订阅源。"""
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
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("refresh_feeds", {"title": "RSS 刷新", "message": "MCP 请求刷新全部订阅源"})


def rss_preview(hash_, link=""):
    """触发指定 RSS 条目的预览（通过 mcp_inbox IPC）。"""
    from .tools_system_config_gui import _mcp_inbox_command
    return _mcp_inbox_command("rss_preview", {"hash": hash_, "link": link})


def rss_stats():
    """查看各订阅源的条目统计。"""
    from .tools_rss_feeds import _rss_store
    return _rss_store().get_stats()


def rss_tags():
    """列出所有 RSS 标签（来源标签）。"""
    from .tools_rss_feeds import _rss_store
    return _rss_store().get_tags_and_groups()


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
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
        "name": "rss_preview",
        "description": "触发指定 RSS 条目的预览（通过 mcp_inbox IPC，需要 GUI 正在运行）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "必填，条目 hash"},
                "link": {"type": "string", "description": "可选，条目链接 URL"},
            },
            "required": ["hash"],
        },
        "handler": lambda a: rss_preview(a["hash"], a.get("link", "")),
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
]