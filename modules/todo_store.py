"""待办数据访问层（无 GUI 依赖）：todo_notes 表 CRUD。

DDL/迁移/连接见 modules/todo_store_conn.py（唯一真源，AGENTS.md 单文件 ≤250 行约束）。
自定义状态 CRUD 见 modules/todo_store_statuses.py，此处 re-export 保持向后兼容。
"""
from core.constants import DB_PATH  # noqa: F401  (conftest 隔离 fixture 的 patch 目标)
from core.perf import trace

from .todo_store_conn import _get_conn, _migrate_statuses, _now  # noqa: F401


def add_todo(title, content="", priority=1, due_date=None, category="", status_id=None):
    ensure_category(category)
    conn = _get_conn()
    now = _now()
    if status_id is None:
        todo_status_id = conn.execute(
            "SELECT id FROM todo_statuses WHERE name = '待办'"
        ).fetchone()[0]
        done = 0
    else:
        todo_status_id = status_id
        row = conn.execute(
            "SELECT is_done_like FROM todo_statuses WHERE id = ?", (status_id,)
        ).fetchone()
        done = 1 if (row and row[0]) else 0
    cur = conn.execute(
        "INSERT INTO todo_notes (title, content, priority, category, done, status_id, due_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title, content, priority, category, done, todo_status_id, due_date, now, now),
    )
    conn.commit()
    todo_id = cur.lastrowid
    conn.close()
    return todo_id


def update_todo(todo_id, **kwargs):
    if "category" in kwargs:
        ensure_category(kwargs["category"])
    conn = _get_conn()
    fields = []
    values = []
    for key in ("title", "content", "priority", "category", "done", "due_date",
                "status_id", "created_at"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
    # status_id 与 done 同步：status_id 优先，按 is_done_like 推导 done
    if "status_id" in kwargs:
        sid = kwargs["status_id"]
        row = conn.execute(
            "SELECT is_done_like FROM todo_statuses WHERE id = ?", (sid,)
        ).fetchone()
        if row is not None:
            pairs = [(f, v) for f, v in zip(fields, values) if f != "done = ?"]
            fields = [p[0] for p in pairs]
            values = [p[1] for p in pairs]
            fields.append("done = ?")
            values.append(1 if row[0] else 0)
    if not fields:
        conn.close()
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(todo_id)
    conn.execute(f"UPDATE todo_notes SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def set_todos_done(todo_ids, done):
    """批量设置多条待办的完成状态（单条 UPDATE，避免 N 次单行写）。"""
    ids = [i for i in todo_ids if i is not None]
    if not ids:
        return
    conn = _get_conn()
    placeholders = ", ".join("?" for _ in ids)
    conn.execute(
        f"UPDATE todo_notes SET done = ?, updated_at = ? WHERE id IN ({placeholders})",
        [1 if done else 0, _now(), *ids],
    )
    conn.commit()
    conn.close()


def delete_todo(todo_id):
    conn = _get_conn()
    conn.execute("DELETE FROM todo_notes WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()


@trace()
def get_todos(done=None, keyword=None, order="created_at", category=None):
    conn = _get_conn()
    query = ("SELECT id, title, content, priority, category, done, status_id, "
             "due_date, created_at, updated_at FROM todo_notes")
    conditions = []
    params = []
    if done is not None:
        conditions.append("done = ?")
        params.append(done)
    if keyword:
        conditions.append("(title LIKE ? OR content LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])
    if category:
        conditions.append("category = ?")
        params.append(category)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    order_map = {
        "created_at": "created_at DESC",
        "priority": "priority DESC, created_at DESC",
        "due_date": "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC",
    }
    query += f" ORDER BY {order_map.get(order, 'created_at DESC')}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "content": r[2], "priority": r[3],
         "category": r[4] or "", "done": r[5], "status_id": r[6],
         "due_date": r[7], "created_at": r[8], "updated_at": r[9]}
        for r in rows
    ]


def get_categories():
    """返回全部类别名（读 todo_categories 表，见 todo_store_categories）。"""
    return _get_categories()


def get_todo_count():
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM todo_notes WHERE done = 0").fetchone()
    conn.close()
    return row[0] if row else 0


# 自定义状态（todo_statuses）数据层切片：实现见 modules/todo_store_statuses.py
# （AGENTS.md 单文件 ≤250 行约束）。此处 re-export 保持向后兼容导入路径。
from .todo_store_statuses import (  # noqa: E402
    add_status, delete_status, get_or_create_status, get_statuses,
    rename_status, set_status_color,
)

# 选项→颜色数据层切片（todo 16 多颜色）
from .todo_store_option_colors import (  # noqa: E402
    get_option_color, set_option_color, get_all_option_colors, delete_option_color,
)

# 类别（todo_categories）数据层切片：实现见 modules/todo_store_categories.py
# （AGENTS.md 单文件 ≤250 行约束）。此处 re-export 保持向后兼容导入路径；
# get_categories 以 _get_categories 别名导入，供上方委托函数调用。
from .todo_store_categories import (  # noqa: E402
    add_category, delete_category, ensure_category, rename_category,
    get_categories as _get_categories,
)