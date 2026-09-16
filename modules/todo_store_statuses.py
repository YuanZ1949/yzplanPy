"""待办自定义状态（todo_statuses）数据层切片。

从 modules/todo_store.py 拆分（AGENTS.md 单文件 ≤250 行约束）。
连接/迁移来自 modules/todo_store_conn.py（唯一真源），无循环导入。
"""
from .todo_store_conn import _STATUS_TODO, _get_conn


def get_statuses():
    """返回全部状态，按 sort_order ASC, id ASC 排序。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, name, color, sort_order, is_done_like FROM todo_statuses "
        "ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "color": r[2],
         "sort_order": r[3], "is_done_like": r[4]}
        for r in rows
    ]


def add_status(name, color=None, sort_order=0):
    """新增自定义状态（is_done_like=0）。同名抛 IntegrityError。"""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO todo_statuses (name, color, sort_order, is_done_like) VALUES (?, ?, ?, 0)",
        (name, color, sort_order),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def rename_status(status_id, new_name):
    """重命名状态。重名为已存在名字抛 IntegrityError。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE todo_statuses SET name = ? WHERE id = ?", (new_name, status_id)
    )
    conn.commit()
    conn.close()


def set_status_color(status_id, color):
    """设置状态颜色。"""
    conn = _get_conn()
    conn.execute(
        "UPDATE todo_statuses SET color = ? WHERE id = ?", (color, status_id)
    )
    conn.commit()
    conn.close()


def delete_status(status_id):
    """删除状态；引用它的 todos 回退到「待办」（done 同步为 0）。

    内置「待办」不可删除（抛 ValueError）。
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT name FROM todo_statuses WHERE id = ?", (status_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return
    if row[0] == _STATUS_TODO:
        conn.close()
        raise ValueError("不能删除内置「待办」状态")
    todo_id = conn.execute(
        "SELECT id FROM todo_statuses WHERE name = ?", (_STATUS_TODO,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE todo_notes SET status_id = ?, done = 0 WHERE status_id = ?",
        (todo_id, status_id),
    )
    conn.execute("DELETE FROM todo_statuses WHERE id = ?", (status_id,))
    conn.commit()
    conn.close()


def get_or_create_status(name):
    """按名字查找状态，不存在则创建（用于"单元格内重命名"路径）。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM todo_statuses WHERE name = ?", (name,)
    ).fetchone()
    if row:
        conn.close()
        return row[0]
    cur = conn.execute(
        "INSERT INTO todo_statuses (name, color, sort_order, is_done_like) VALUES (?, NULL, 0, 0)",
        (name,),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid