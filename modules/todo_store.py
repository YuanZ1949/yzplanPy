"""待办数据访问层（无 GUI 依赖）：todo_notes 表的 DDL 唯一真源。"""
import sqlite3
from datetime import datetime

from core.constants import DB_PATH
from core.perf import trace


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
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
    cols = [r[1] for r in conn.execute("PRAGMA table_info(todo_notes)").fetchall()]
    if "category" not in cols:
        conn.execute("ALTER TABLE todo_notes ADD COLUMN category TEXT DEFAULT ''")
    conn.commit()
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_todo(title, content="", priority=1, due_date=None, category=""):
    conn = _get_conn()
    now = _now()
    cur = conn.execute(
        "INSERT INTO todo_notes (title, content, priority, category, done, due_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
        (title, content, priority, category, due_date, now, now),
    )
    conn.commit()
    todo_id = cur.lastrowid
    conn.close()
    return todo_id


def update_todo(todo_id, **kwargs):
    conn = _get_conn()
    fields = []
    values = []
    for key in ("title", "content", "priority", "category", "done", "due_date"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
    if not fields:
        conn.close()
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(todo_id)
    conn.execute(f"UPDATE todo_notes SET {', '.join(fields)} WHERE id = ?", values)
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
    query = "SELECT id, title, content, priority, category, done, due_date, created_at, updated_at FROM todo_notes"
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
         "category": r[4] or "", "done": r[5], "due_date": r[6],
         "created_at": r[7], "updated_at": r[8]}
        for r in rows
    ]


def get_categories():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT category FROM todo_notes WHERE category != '' ORDER BY category"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_todo_count():
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM todo_notes WHERE done = 0").fetchone()
    conn.close()
    return row[0] if row else 0