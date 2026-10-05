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

# --- resolve_dark 双 patch 辅助（P-3 主题测试共享） ---
# 背景：theme_palette() 走 from .base import resolve_dark（模块级绑定），
# 但其他代码可能走 from core.theme import resolve_dark（包级绑定），
# 必须双 patch 才能一致生效。测试结束后必须 _restore_dark() 还原，
# 否则泄漏的 patch 会让同进程后续主题切换回归测试取错色板
# （#e8e8e8 事故：test_theme_refresh_qss_child 在浅色下仍取暗色板）。
_ORIG_RESOLVE_DARK = {}


def _force_dark(dark):
    import core.theme.base as base
    import core.theme as pkg
    _ORIG_RESOLVE_DARK.setdefault("base", base.resolve_dark)
    _ORIG_RESOLVE_DARK.setdefault("pkg", pkg.resolve_dark)
    base.resolve_dark = lambda mode: dark
    pkg.resolve_dark = lambda mode: dark


def _restore_dark():
    """还原 _force_dark 的 patch，避免污染同进程后续测试（如主题切换回归）。"""
    import core.theme.base as base
    import core.theme as pkg
    if "base" in _ORIG_RESOLVE_DARK:
        base.resolve_dark = _ORIG_RESOLVE_DARK.pop("base")
    if "pkg" in _ORIG_RESOLVE_DARK:
        pkg.resolve_dark = _ORIG_RESOLVE_DARK.pop("pkg")


@pytest.fixture(scope="session")
def qapp():
    """session 级 QApplication（AGENTS.md 规则 3：只在 conftest 创建）。

    测试文件通过参数注入获取，禁止模块顶层 QApplication(...)。
    QT_QPA_PLATFORM 只允许 setdefault（不劫持已显式设置的环境）。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """所有测试默认使用临时数据库，绝不触碰生产 data/app.db。"""
    db = tmp_path / "test.db"

    import modules.todo_store as todo_store
    import modules.blog.store as blog_store

    monkeypatch.setattr(todo_store, "DB_PATH", str(db))
    monkeypatch.setattr(blog_store, "DB_PATH", str(db))

    # router_admin 的两个持久化文件同理。事故背景（2026-09-29）：
    # tests/test_router_wan.py 用假 session 驱动 wan_save_worker →
    # backup_then_write → backup.save_backup()，假 session 对任何命令都回
    # "YZ_WRITE_OK"，于是 4 份「备份」内容全是 YZ_WRITE_OK 而不是配置正文，
    # 被写进了生产的 data/router_admin/backups/。危害不是那 4 个文件，而是
    # **安全网失效**：备份里没有可回滚的内容，写配置出事时 read_backup()
    # 取回来的东西毫无意义。这两个模块都在调用时读模块全局（与上面 DB_PATH
    # 同一模式），所以 monkeypatch 模块属性即可完全拦截。
    import modules.router_admin.store as router_store
    import modules.router_admin.backup as router_backup

    monkeypatch.setattr(router_store, "SETTINGS_PATH",
                        str(tmp_path / "router_settings.json"))
    monkeypatch.setattr(router_backup, "BACKUP_DIR",
                        str(tmp_path / "router_backups"))

    # right_menu 账本同理：store 的 STATE_PATH/BACKUP_DIR/TEMPLATES_DIR 都在
    # 调用时读模块全局（与上面两处同一模式），所以 monkeypatch 即可完全拦截。
    # 不隔离的话，一次 backup_snapshot() 测试就会往生产 data/right_menu/backups/
    # 里写快照——和 router_admin 那次「备份全是 YZ_WRITE_OK」一样是脏数据落盘。
    import modules.right_menu.store as rm_store

    monkeypatch.setattr(rm_store, "STATE_PATH",
                        str(tmp_path / "right_menu" / "state.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR",
                        str(tmp_path / "right_menu" / "backups"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR",
                        str(tmp_path / "right_menu" / "templates"))

    # 调用生产建表入口（CREATE TABLE IF NOT EXISTS 幂等），使测试对库/表存在性免疫；
    # schema 单一真源，不复制 DDL。
    todo_store._get_conn().close()
    blog_store._get_conn().close()

    return db


def pytest_configure(config):
    """注册 qpa marker：windows QPA 真实渲染测试（真实字体/真实样式，
    需窗口会话；无会话时对应测试文件整模块 skip）。"""
    config.addinivalue_line(
        "markers",
        "qpa: windows QPA 真实渲染测试（需窗口会话，无 QApplication 时整模块 skip）")