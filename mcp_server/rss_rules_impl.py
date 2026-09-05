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

