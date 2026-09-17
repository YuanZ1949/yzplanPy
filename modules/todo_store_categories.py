"""待办类别（todo_categories）数据层切片。

从 modules/todo_store.py 拆分（AGENTS.md 单文件 ≤250 行约束）。
连接/迁移来自 modules/todo_store_conn.py（唯一真源），无循环导入。

背景：类别此前由 `SELECT DISTINCT category FROM todo_notes` 推导，
没有任何便签引用某类别时该类别即消失。本切片把类别持久化到
独立表 todo_categories，写入路径经 ensure_category 保证手输新类别留存。

注意：所有函数用 try/finally 保证连接关闭 —— 抛 IntegrityError/ValueError
时若连接不关闭，被捕获异常的 traceback 会持有帧（连带打开的写锁），
后续连接会撞上 `database is locked`。
"""
from .todo_store_conn import _get_conn


def get_categories():
    """返回全部类别名，按 sort_order ASC, name ASC 排序（list[str]）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM todo_categories ORDER BY sort_order, name"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def add_category(name):
    """新增类别。空名/纯空白名抛 ValueError；重名抛 IntegrityError。"""
    if not name or not name.strip():
        raise ValueError("类别名不能为空")
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO todo_categories (name) VALUES (?)", (name,)
        )
        conn.commit()
    finally:
        conn.close()
    return cur.lastrowid


def rename_category(old, new):
    """重命名类别，并同步引用它的 todo_notes 行。

    新名字已存在时抛 IntegrityError（UNIQUE 约束，事务未提交，不改库）。
    """
    if not new or not new.strip():
        raise ValueError("类别名不能为空")
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE todo_categories SET name = ? WHERE name = ?", (new, old)
        )
        conn.execute(
            "UPDATE todo_notes SET category = ? WHERE category = ?", (new, old)
        )
        conn.commit()
    finally:
        conn.close()


def delete_category(name):
    """删除类别；引用它的 todo_notes 行 category 置 ''（不残留孤儿）。

    删除不存在的类别名是幂等空操作（不抛异常）。
    """
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE todo_notes SET category = '' WHERE category = ?", (name,)
        )
        conn.execute("DELETE FROM todo_categories WHERE name = ?", (name,))
        conn.commit()
    finally:
        conn.close()


def ensure_category(name):
    """写入路径 upsert：类别不存在则创建（空名/纯空白名忽略）。"""
    if not name or not name.strip():
        return
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO todo_categories (name) VALUES (?)", (name,)
        )
        conn.commit()
    finally:
        conn.close()