"""webview_control 主表条目隐藏：持久化 + 视图过滤 + 恢复对话框。

覆盖 Task 4：load_hidden_hosts/save_hidden_hosts 往返与损坏数据兜底；
_visible_hosts 纯函数过滤；子进程冒烟——预置隐藏 A 后主表只显示 B/C、
计数含「已隐藏 1」、隐藏 B 后主表剩 1、恢复对话框 Delete 解除 + 全部恢复。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139）。
from core.qt_bootstrap import import_qt

_, QtCore, _, QtWidgets = import_qt()

from modules.webview_control.config import load_hidden_hosts, save_hidden_hosts
from modules.webview_control.hidden_dialog import _visible_hosts

QApplication = QtWidgets.QApplication


def _norm(p):
    return os.path.normcase(p).lower()


class _FakeConfig:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):
        pass


def test_hidden_hosts_roundtrip_normalizes():
    cfg = _FakeConfig()
    save_hidden_hosts(cfg, [r"C:\Apps\A.EXE", r"c:\apps\b.exe"])
    loaded = load_hidden_hosts(cfg)
    assert loaded == [_norm(r"C:\Apps\A.EXE"), _norm(r"C:\Apps\b.exe")]
    assert all(x.islower() for x in loaded)


def test_hidden_hosts_missing_or_corrupt_returns_empty():
    cfg = _FakeConfig()
    assert load_hidden_hosts(cfg) == []
    cfg.data["webview"] = {"hidden_hosts": "not-a-list"}
    assert load_hidden_hosts(cfg) == []
    cfg.data["webview"] = {"hidden_hosts": [1, None, ""]}
    assert load_hidden_hosts(cfg) == []


def test_visible_hosts_filters_hidden_keeps_order():
    hosts = [
        {"exe": _norm(r"C:\Apps\A.exe")},
        {"exe": _norm(r"C:\Apps\B.exe")},
        {"exe": _norm(r"C:\Apps\C.exe")},
    ]
    got = _visible_hosts(hosts, {_norm(r"C:\Apps\B.exe")})
    assert [h["exe"] for h in got] == [_norm(r"C:\Apps\A.exe"), _norm(r"C:\Apps\C.exe")]


def test_webview_hidden_smoke_subprocess():
    """Subprocess isolation: 隐藏过滤 + 恢复对话框 (icuuc.dll guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_webview_hidden_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_webview_hidden.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )
    assert "WEBVIEW_HIDDEN_OK" in result.stdout.decode()


def test_webview_hidden_smoke_child(monkeypatch):
    """Child: 预置隐藏 A → 主表 2 行；隐藏 B → 1 行；恢复对话框 Delete/全部恢复。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel
    from modules.webview_control.module import Module
    from modules.webview_control.hidden_dialog import show_hidden_dialog

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    class _FakeConfig:
        def __init__(self):
            self.data = {}

        def get(self, key, default=None):
            cur = self.data
            for part in key.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return default
                cur = cur[part]
            return cur

        def set(self, key, value):
            cur = self.data
            parts = key.split(".")
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = value

        def save(self):
            pass

    class _FakeContext:
        def __init__(self, config):
            self.config = config

    cfg = _FakeConfig()
    cfg.data["webview"] = {"hidden_hosts": [_norm(r"C:\Apps\A.exe")]}

    def _fake_scan(blocked):
        return [
            {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
             "procs": [], "webview_count": 1, "connections": 0,
             "blocked": False, "user_data_dirs": []},
            {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
             "procs": [], "webview_count": 1, "connections": 0,
             "blocked": False, "user_data_dirs": []},
            {"exe": _norm(r"C:\Apps\C.exe"), "name": "C", "running": True,
             "procs": [], "webview_count": 1, "connections": 0,
             "blocked": False, "user_data_dirs": []},
        ]

    monkeypatch.setattr("modules.webview_control.page.scan_hosts", _fake_scan)

    mod = Module(_FakeContext(cfg))
    page = mod.create_page(None)
    page.resize(760, 600)
    page.show()
    for _ in range(5):
        app.processEvents()
        QtCore.QThread.msleep(20)

    tables = [t for t in page.findChildren(QtWidgets.QTableWidget)
              if t.columnCount() == 8]
    assert tables, "未找到合并表"
    table = tables[0]
    assert table.rowCount() == 2, f"A 隐藏后主表应 2 行，实际 {table.rowCount()}"

    counts = [l.text() for l in page.findChildren(BodyLabel) if "个程序" in l.text()]
    assert counts, "未找到计数标签"
    assert "已隐藏 1" in counts[0], f"计数应含「已隐藏 1」，实际 {counts[0]}"

    # 隐藏 B（等价「隐藏此程序」动作）
    hidden = load_hidden_hosts(cfg)
    hidden.append(_norm(r"C:\Apps\B.exe"))
    save_hidden_hosts(cfg, hidden)
    getattr(mod, "_page_refresh")()
    for _ in range(3):
        app.processEvents()
    assert table.rowCount() == 1, f"隐藏 B 后主表应 1 行，实际 {table.rowCount()}"

    # 恢复对话框：Delete 解除 + 全部恢复
    calls = []
    dlg = show_hidden_dialog(
        page, [_norm(r"C:\Apps\A.exe"), _norm(r"C:\Apps\B.exe")], calls.append)
    lst = dlg._list
    assert lst.count() == 2, f"对话框应列 2 项，实际 {lst.count()}"
    lst.setCurrentRow(0)
    dlg._on_delete_pressed()
    assert calls == [_norm(r"C:\Apps\A.exe")], f"Delete 应解除第 0 项，实际 {calls}"
    assert lst.count() == 1, f"Delete 后列表应剩 1 项，实际 {lst.count()}"
    btn_all = [b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == "全部恢复"]
    assert btn_all, "未找到「全部恢复」按钮"
    btn_all[0].click()
    assert calls == [_norm(r"C:\Apps\A.exe"), _norm(r"C:\Apps\B.exe")], (
        f"全部恢复应解除剩余项，实际 {calls}")

    page.close()
    page.deleteLater()
    dlg.close()
    dlg.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("WEBVIEW_HIDDEN_OK")


# ── Task 18: 右键菜单操作在「全部」默认视图下回归锁定 ─────────────────────

class _FakeContext:
    def __init__(self, config):
        self.config = config


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_page(scan_data, host_log_data, blocked=None, hidden=None, monkeypatch=None):
    """Helper: build the merged webview page with controlled scan + log data."""
    from modules.webview_control.module import Module

    _app()

    cfg = _FakeConfig()
    if blocked:
        cfg.data["webview"] = {"blocked_hosts": sorted(blocked)}
    if hidden:
        cfg.data.setdefault("webview", {})["hidden_hosts"] = hidden

    mod = Module(_FakeContext(cfg))
    mod.host_log = list(host_log_data)

    import modules.webview_control.page as page_mod
    if monkeypatch is not None:
        monkeypatch.setattr(page_mod, "scan_hosts", lambda blocked: list(scan_data))

    page = mod.create_page(None)
    page.resize(900, 600)
    page.show()
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)

    return mod, page


def _table(page):
    return page.findChildren(QtWidgets.QTableWidget)[0]


def _pump():
    for _ in range(3):
        QApplication.processEvents()


def _status_combo(page):
    from qfluentwidgets import ComboBox
    return page.findChildren(ComboBox)[0]


def _invoke_menu_action(table, row, text, monkeypatch):
    """右键第 row 行并选择文字为 text 的菜单项。

    拦截 QMenu.exec_ 返回目标 action，避免真实弹窗阻塞；走真实的
    customContextMenuRequested → _menu 链路（page.py:501-549）。
    """
    def fake_exec(menu, *args, **kwargs):
        for a in menu.actions():
            if a.text() == text:
                return a
        return None

    monkeypatch.setattr(QtWidgets.QMenu, "exec_", fake_exec)
    pos = table.visualItemRect(table.item(row, 0)).center()
    table.customContextMenuRequested.emit(pos)


def _two_hosts():
    return [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]


def test_hide_via_menu_removes_row_under_all_default(monkeypatch):
    """默认「全部」视图下，右键「隐藏此程序」→ 行消失（真隐藏而非被过滤）。"""
    mod, page = _make_page(scan_data=_two_hosts(), host_log_data=[],
                           monkeypatch=monkeypatch)
    table = _table(page)
    assert _status_combo(page).currentData() == "all"
    assert table.rowCount() == 2

    _invoke_menu_action(table, 0, "隐藏此程序", monkeypatch)
    _pump()

    assert table.rowCount() == 1, "隐藏后「全部」视图应只剩 1 行"
    assert table.item(0, 0).text() == "B"
    # 视图仍是「全部」→ 行消失证明是真隐藏，不是被视图过滤
    assert _status_combo(page).currentData() == "all"
    assert _norm(r"C:\Apps\A.exe") in load_hidden_hosts(mod.context.config)

    page.close()
    page.deleteLater()


def test_restore_via_menu_returns_row(monkeypatch):
    """右键「恢复显示」→ 对话框「全部恢复」→ 行回到「全部」视图。"""
    mod, page = _make_page(scan_data=_two_hosts(), host_log_data=[],
                           monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 2

    _invoke_menu_action(table, 0, "隐藏此程序", monkeypatch)
    _pump()
    assert table.rowCount() == 1

    _invoke_menu_action(table, 0, "恢复显示（显示所有隐藏项）", monkeypatch)
    _pump()

    dialogs = [w for w in QApplication.topLevelWidgets()
               if isinstance(w, QtWidgets.QDialog) and w.isVisible()
               and w.windowTitle() == "显示所有隐藏项"]
    assert dialogs, "「恢复显示」未打开隐藏项对话框"
    dlg = dialogs[0]
    btn_all = [b for b in dlg.findChildren(QtWidgets.QPushButton) if b.text() == "全部恢复"]
    assert btn_all, "未找到「全部恢复」按钮"
    btn_all[0].click()
    _pump()

    assert table.rowCount() == 2, "恢复后「全部」视图应回到 2 行"
    assert load_hidden_hosts(mod.context.config) == []
    dlg.close()
    dlg.deleteLater()
    page.close()
    page.deleteLater()


def test_hidden_state_persists_across_rebuild(monkeypatch):
    """隐藏状态经 config 持久化：重建页面后仍不显示隐藏行。"""
    mod, page = _make_page(scan_data=_two_hosts(), host_log_data=[],
                           monkeypatch=monkeypatch)
    table = _table(page)
    _invoke_menu_action(table, 0, "隐藏此程序", monkeypatch)
    _pump()
    assert table.rowCount() == 1
    page.close()
    page.deleteLater()

    # 用同一 config 重建 Module + 页面 → A 仍隐藏
    from modules.webview_control.module import Module
    mod2 = Module(_FakeContext(mod.context.config))
    mod2.host_log = list(mod.host_log)
    page2 = mod2.create_page(None)
    page2.resize(900, 600)
    page2.show()
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)

    table2 = _table(page2)
    assert table2.rowCount() == 1, "重建后隐藏行不应出现"
    assert table2.item(0, 0).text() == "B"
    page2.close()
    page2.deleteLater()


def test_allow_block_delete_actions_under_all_default(monkeypatch):
    """「全部」默认视图下：菜单封禁/放行切换与「删除」按钮仍生效。"""
    host_log_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-01 00:00:00",
         "status": "pending"},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-01 00:00:00",
         "status": "pending"},
    ]
    mod, page = _make_page(scan_data=_two_hosts(), host_log_data=host_log_data,
                           monkeypatch=monkeypatch)
    table = _table(page)
    assert _status_combo(page).currentData() == "all"
    assert table.rowCount() == 2
    a_exe = _norm(r"C:\Apps\A.exe")

    # 菜单「封禁」→ A 进入封禁集合
    _invoke_menu_action(table, 0, "封禁", monkeypatch)
    _pump()
    assert a_exe in mod.blocked

    # 菜单「放行」→ A 移出封禁集合
    _invoke_menu_action(table, 0, "放行", monkeypatch)
    _pump()
    assert a_exe not in mod.blocked

    # 「删除」按钮 → 记录从 host_log 移除
    cell = table.cellWidget(0, 7)
    btns = {b.text(): b for b in cell.findChildren(QtWidgets.QPushButton)}
    btns["删除"].click()
    _pump()
    assert a_exe not in mod.host_log
    assert a_exe not in mod.blocked

    page.close()
    page.deleteLater()