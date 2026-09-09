"""DB 隔离回归测试。

2026-09-08 事故：test_todo_notes_ui.py 直接运行在生产 data/app.db 上，
清空了用户 12 条真实便签。本文件锁定隔离机制，若 conftest 的 autouse
fixture 被移除或失效，以下测试必须失败。
"""
import sqlite3

import modules.todo_store as todo_store
from core.constants import DB_PATH as PROD_DB_PATH


def _prod_todo_count():
    """生产库 todo_notes 行数；表不存在（干净环境）时返回 -1。"""
    try:
        return sqlite3.connect(PROD_DB_PATH).execute(
            "SELECT COUNT(*) FROM todo_notes"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        return -1


def test_todo_store_writes_never_leak_to_production_db():
    """todo_store 的写入必须落在临时 DB，生产库行数前后不变。"""
    before = _prod_todo_count()

    for i in range(3):
        todo_store.add_todo(f"__isolation_probe_{i}__")

    after = _prod_todo_count()
    assert after == before


def test_todo_store_db_path_is_patched_in_test():
    """测试内部 todo_store.DB_PATH 必须指向临时文件而非生产库。"""
    assert todo_store.DB_PATH != PROD_DB_PATH
    assert "app.db" not in todo_store.DB_PATH