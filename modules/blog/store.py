"""Blog 数据访问层（无 GUI 依赖）：blog_posts 表的 DDL 唯一真源。"""
import sqlite3
from datetime import datetime

from core.constants import DB_PATH
from core.perf import trace


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_post(title, content=""):
    """新增文章；标题为空抛 ValueError，不回写。"""
    if not title or not str(title).strip():
        raise ValueError("标题不能为空")
    conn = _get_conn()
    now = _now()
    cur = conn.execute(
        "INSERT INTO blog_posts (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title, content, now, now),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return post_id


def update_post(post_id, title=None, content=None):
    """更新文章字段；标题为空抛 ValueError。"""
    conn = _get_conn()
    fields = []
    values = []
    if title is not None:
        if not str(title).strip():
            conn.close()
            raise ValueError("标题不能为空")
        fields.append("title = ?")
        values.append(title)
    if content is not None:
        fields.append("content = ?")
        values.append(content)
    if not fields:
        conn.close()
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(post_id)
    conn.execute(f"UPDATE blog_posts SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_post(post_id):
    conn = _get_conn()
    conn.execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()


@trace()
def list_posts(order="updated_at"):
    """列出文章；order ∈ updated_at / created_at / title。"""
    conn = _get_conn()
    order_map = {
        "updated_at": "updated_at DESC",
        "created_at": "created_at DESC",
        "title": "title COLLATE NOCASE ASC",
    }
    query = (
        "SELECT id, title, content, created_at, updated_at FROM blog_posts "
        f"ORDER BY {order_map.get(order, 'updated_at DESC')}"
    )
    rows = conn.execute(query).fetchall()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "content": r[2], "created_at": r[3], "updated_at": r[4]}
        for r in rows
    ]


def get_post(post_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, title, content, created_at, updated_at FROM blog_posts WHERE id = ?",
        (post_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {"id": row[0], "title": row[1], "content": row[2], "created_at": row[3], "updated_at": row[4]}