"""待办数据访问层共享连接/迁移切片（DDL 唯一真源）。

从 modules/todo_store.py 拆分（AGENTS.md 单文件 ≤250 行约束），
供 todo_store 与 todo_store_statuses 共用，避免模块级循环导入。

DB_PATH 从 modules.todo_store 惰性读取：tests/conftest.py 的 autouse 隔离
fixture 通过 monkeypatch.setattr(todo_store, "DB_PATH", ...) 重定向数据库，
必须保证 _get_conn 在调用时读取 todo_store 模块命名空间里的 DB_PATH。
"""
import sqlite3

# 内置状态名（迁移种子）
_STATUS_TODO = "待办"
_STATUS_DONE = "已完成"


def _db_path():
    from modules.todo_store import DB_PATH
    return DB_PATH


def _get_conn():
    conn = sqlite3.connect(_db_path())
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
    if "status_id" not in cols:
        conn.execute("ALTER TABLE todo_notes ADD COLUMN status_id INTEGER")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT,
            sort_order INTEGER DEFAULT 0,
            is_done_like INTEGER DEFAULT 0
        )
    """)
    _migrate_statuses(conn)
    conn.commit()
    return conn


def _migrate_statuses(conn=None):
    """幂等迁移：种子内置状态 + 已有行 status_id 回填/校正。

    - 内置「待办」(is_done_like=0) 与「已完成」(is_done_like=1) 仅在缺失时插入。
    - 已有行按 done 回填 status_id；仅处理 status_id 为 NULL 或指向内置状态的行，
      绝不覆盖用户自定义状态。
    - 重复调用安全：不重复插入、不覆盖自定义状态。
    """
    own = conn is None
    if own:
        conn = sqlite3.connect(_db_path())
    conn.execute(
        "INSERT OR IGNORE INTO todo_statuses (name, color, sort_order, is_done_like) VALUES (?, NULL, 0, 0)",
        (_STATUS_TODO,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO todo_statuses (name, color, sort_order, is_done_like) VALUES (?, NULL, 1, 1)",
        (_STATUS_DONE,),
    )
    todo_id = conn.execute(
        "SELECT id FROM todo_statuses WHERE name = ?", (_STATUS_TODO,)
    ).fetchone()[0]
    done_id = conn.execute(
        "SELECT id FROM todo_statuses WHERE name = ?", (_STATUS_DONE,)
    ).fetchone()[0]
    # 回填/校正：done=0 → 待办，done=1 → 已完成；仅动 NULL 或内置状态的行
    conn.execute(
        "UPDATE todo_notes SET status_id = ? WHERE done = 0 AND "
        "(status_id IS NULL OR status_id IN (SELECT id FROM todo_statuses WHERE name IN (?, ?)))",
        (todo_id, _STATUS_TODO, _STATUS_DONE),
    )
    conn.execute(
        "UPDATE todo_notes SET status_id = ? WHERE done = 1 AND "
        "(status_id IS NULL OR status_id IN (SELECT id FROM todo_statuses WHERE name IN (?, ?)))",
        (done_id, _STATUS_TODO, _STATUS_DONE),
    )
    if own:
        conn.commit()
        conn.close()


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")