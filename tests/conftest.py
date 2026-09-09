"""pytest 公共 fixtures。

事故背景（2026-09-08）：tests/test_todo_notes_ui.py 之前直接运行在
生产数据库 data/app.db 上，测试把用户 12 条真实便签全部清空（后已从
WAL checkpoint 恢复）。根因是本文件没有做任何 DB 隔离。

修复：autouse fixture 把 modules.todo_store.DB_PATH 重定向到每个测试
自己的临时数据库。todo_store 的 _get_conn() 在每次调用时读取模块全局
DB_PATH，因此 monkeypatch 模块属性即可完全拦截（与 test_blog_store.py
中已被证实的隔离模式一致）。子进程 pytest（test_todo_notes_ui.py 的
0xC0000005 隔离测试）同样经过本 conftest，也会获得独立的临时 DB。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """所有测试默认使用临时数据库，绝不触碰生产 data/app.db。"""
    db = tmp_path / "test.db"

    import modules.todo_store as todo_store
    import modules.blog.store as blog_store

    monkeypatch.setattr(todo_store, "DB_PATH", str(db))
    monkeypatch.setattr(blog_store, "DB_PATH", str(db))

    # 调用生产建表入口（CREATE TABLE IF NOT EXISTS 幂等），使测试对库/表存在性免疫；
    # schema 单一真源，不复制 DDL。
    todo_store._get_conn().close()
    blog_store._get_conn().close()

    return db