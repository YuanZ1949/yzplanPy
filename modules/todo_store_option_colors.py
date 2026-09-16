"""待办「选项→颜色」数据层切片（todo 16 多颜色）。

存储优先级/类别等选项的自定义颜色（状态色存 todo_statuses.color，见
todo_store_statuses.py）。表结构 DDL 见 modules/todo_store_conn.py（唯一真源）。
"""
from .todo_store_conn import _get_conn


def get_option_color(column, option_value):
    """读取某列某选项的存储色；未设置返回 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT color FROM todo_option_colors WHERE column = ? AND option_value = ?",
        (column, option_value),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def set_option_color(column, option_value, color):
    """写入/覆盖某列某选项的颜色（upsert）。"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO todo_option_colors (column, option_value, color) VALUES (?, ?, ?) "
        "ON CONFLICT(column, option_value) DO UPDATE SET color = excluded.color",
        (column, option_value, color),
    )
    conn.commit()
    conn.close()


def get_all_option_colors():
    """返回 {(column, option_value): color} 全量映射。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT column, option_value, color FROM todo_option_colors"
    ).fetchall()
    conn.close()
    return {(r[0], r[1]): r[2] for r in rows}


def delete_option_color(column, option_value):
    """删除某列某选项的颜色记录。"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM todo_option_colors WHERE column = ? AND option_value = ?",
        (column, option_value),
    )
    conn.commit()
    conn.close()