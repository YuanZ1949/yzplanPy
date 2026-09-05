"""MCP 工具切片：便签/待办 (todo_*)。

handler 保持函数内 lazy import 数据层（modules.todo_store），顶层零依赖。
"""

# ── 便签/待办 ─────────────────────────────────────────────────────────

def todo_add(title, content="", priority=1, due_date=None, category=""):
    from modules.todo_store import add_todo, get_todos
    if not title or not str(title).strip():
        raise ValueError("title 不能为空")
    tid = add_todo(str(title).strip(), str(content or ""), int(priority),
                   str(category or ""), due_date or None)
    return [it for it in get_todos() if it["id"] == tid]


def todo_list(done=None, keyword=None, category=None, order="created_at", limit=500, todo_id=None):
    from modules.todo_store import get_todos
    if done is not None:
        if str(done).lower() in ("1", "true", "done", "yes", "已完成"):
            done = 1
        elif str(done).lower() in ("0", "false", "pending", "no", "待办", "未完成"):
            done = 0
        else:
            done = int(done)
    items = get_todos(done=done, keyword=keyword, order=order,
                      category=str(category) if category else None)
    if todo_id is not None:
        tid = int(todo_id)
        items = [it for it in items if it["id"] == tid]
    if str(order) == "id":
        items = sorted(items, key=lambda it: it["id"])
    return items[:int(limit)]


def todo_update(id_, **_kwargs):
    from modules.todo_store import get_todos, update_todo
    tid = int(id_)
    cur_todo = next((it for it in get_todos() if it["id"] == tid), None)
    if not cur_todo:
        raise ValueError(f"找不到 id={id_} 的待办")
    allowed = ("title", "content", "priority", "category", "done", "due_date")
    sets = {k: _kwargs[k] for k in allowed if k in _kwargs}
    if not sets:
        return cur_todo
    update_todo(tid, **sets)
    return [it for it in get_todos() if it["id"] == tid]


def todo_delete(id_):
    from modules.todo_store import delete_todo
    delete_todo(int(id_))
    return {"deleted": True}


def todo_stats():
    from modules.todo_store import get_todos
    items = get_todos()
    total = len(items)
    done = sum(1 for it in items if it["done"] == 1)
    return {"total": total, "done": done, "pending": total - done}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

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
]