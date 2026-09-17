"""待办数据访问层共享连接/迁移切片（DDL 唯一真源）。

从 modules/todo_store.py 拆分（AGENTS.md 单文件 ≤250 行约束），
供 todo_store 与 todo_store_statuses 共用，避免模块级循环导入。

DB_PATH 从 modules.todo_store 惰性读取：tests/conftest.py 的 autouse 隔离
fixture 通过 monkeypatch.setattr(todo_store, "DB_PATH", ...) 重定向数据库，
必须保证 _get_conn 在调用时读取 todo_store 模块命名空间里的 DB_PATH。
"""
import sqlite3
import time

# 内置状态名（迁移种子）
_STATUS_TODO = "待办"
_STATUS_DONE = "已完成"

# SQLite 忙等待超时（毫秒）：启动期并发连接时等待写锁而非立即抛
# "database is locked"。sqlite3.connect 的 timeout 参数单位是秒，
# 与 PRAGMA busy_timeout 共用同一常量，避免魔法数字散落。
_BUSY_TIMEOUT_MS = 5000
# todo_notes 缺列 ALTER 迁移的 schema 版本（PRAGMA user_version 守卫，
# 每个库文件只迁移一次，进程重启后依然生效）。
_SCHEMA_VERSION = 1
# 迁移失败（锁竞争）时的有限重试次数与指数退避基数（秒）。
_MIGRATION_RETRIES = 3
_MIGRATION_BACKOFF_BASE = 0.05


def _db_path():
    from modules.todo_store import DB_PATH
    return DB_PATH


def _get_conn():
    conn = sqlite3.connect(_db_path(), timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_base_schema(conn)
    _ensure_columns(conn)
    _seed_migrations(conn)
    conn.commit()
    return conn


def _ensure_base_schema(conn):
    """幂等 DDL：全部 CREATE TABLE IF NOT EXISTS（表已存在时零副作用）。"""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT,
            sort_order INTEGER DEFAULT 0,
            is_done_like INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_option_colors (
            column TEXT NOT NULL,
            option_value TEXT NOT NULL,
            color TEXT,
            PRIMARY KEY (column, option_value)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0
        )
    """)


def _alter_add_column(conn, ddl):
    """执行一条缺列 ALTER（独立函数，便于测试注入锁竞争失败）。"""
    conn.execute(ddl)


def _ensure_columns(conn):
    """缺列 ALTER 迁移：每个库文件只执行一次（PRAGMA user_version 守卫）。

    失败（锁竞争）时有限次指数退避重试，而不是直接抛 database is locked。
    列存在性检查保证部分失败后重试可恢复（已加的列不再 ALTER）。
    """
    if conn.execute("PRAGMA user_version").fetchone()[0] >= _SCHEMA_VERSION:
        return
    for attempt in range(_MIGRATION_RETRIES):
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(todo_notes)").fetchall()]
            if "category" not in cols:
                _alter_add_column(
                    conn, "ALTER TABLE todo_notes ADD COLUMN category TEXT DEFAULT ''"
                )
            if "status_id" not in cols:
                _alter_add_column(
                    conn, "ALTER TABLE todo_notes ADD COLUMN status_id INTEGER"
                )
            conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            return
        except sqlite3.OperationalError:
            if attempt == _MIGRATION_RETRIES - 1:
                raise
            time.sleep(_MIGRATION_BACKOFF_BASE * (2 ** attempt))


def _seed_migrations(conn):
    """幂等种子迁移：类别灌入 + 状态回填（重复执行无副作用）。

    INSERT OR IGNORE + name UNIQUE 保证类别不重复插入；_migrate_statuses
    只回填 NULL/内置状态的行，绝不覆盖用户自定义状态。
    """
    conn.execute(
        "INSERT OR IGNORE INTO todo_categories (name) "
        "SELECT DISTINCT category FROM todo_notes "
        "WHERE category IS NOT NULL AND category != ''"
    )
    _migrate_statuses(conn)


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