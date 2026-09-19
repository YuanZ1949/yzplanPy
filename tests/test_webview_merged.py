"""webview_control merged table: scan + interception log into one QTableWidget.

Covers Task 9: 两表合一（一行 = 一个程序）。

验证点:
- 页面有且仅有 1 个 QTableWidget
- 8 列表头完全匹配
- 仅在扫描中出现的程序 → 首次/最近出现 = 当前时间（±容差）
- 在 host_log 中有记录的程序 → 1 行，使用 host_log 时间
- 操作列最小宽度 ≥ 3×56+间距
- delete/hide/restore 路径可调用
- 处置状态下拉过滤保持
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication


_MERGED_HEADERS = [
    "程序名", "程序地址", "链接状态", "封禁开关",
    "首次出现", "最近出现", "处置状态", "操作",
]


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


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


class _FakeContext:
    def __init__(self, config):
        self.config = config


def _make_page(scan_data, host_log_data, blocked=None, hidden=None, monkeypatch=None):
    """Helper: build the merged webview page with controlled scan + log data.

    monkeypatch 提供时用 pytest monkeypatch 持久替换 scan_hosts（测试结束自动还原），
    否则仅临时替换（页面创建后即还原，适用于不再次 refresh 的测试）。
    """
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
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
    else:
        _orig_scan = page_mod.scan_hosts
        page_mod.scan_hosts = lambda blocked: list(scan_data)

    page = mod.create_page(None)
    if monkeypatch is None:
        page_mod.scan_hosts = _orig_scan

    page.resize(900, 600)
    page.show()
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)

    return mod, page


# ── Column structure tests ─────────────────────────────────────────────

def test_merged_table_is_single_qtablewidget():
    """页面有且仅有 1 个 QTableWidget。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    tables = page.findChildren(QtWidgets.QTableWidget)
    assert len(tables) == 1, f"应有且仅有 1 个 QTableWidget，实际 {len(tables)}"
    page.close()
    page.deleteLater()


def test_merged_table_eight_columns():
    """8 列表头完全匹配。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == _MERGED_HEADERS, f"列头不匹配: {headers}"
    assert table.columnCount() == 8
    page.close()
    page.deleteLater()


# ── Data merge tests ───────────────────────────────────────────────────

def test_program_only_in_scan_gets_current_time():
    """仅在扫描中出现的程序 → 首次出现/最近出现 = 当前时间（±2s 容差）。"""
    now_before = time.strftime("%Y-%m-%d %H:%M:%S")
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\ScanOnly.exe"), "name": "ScanOnly",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    now_after = time.strftime("%Y-%m-%d %H:%M:%S")
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    # 程序只在扫描中 → 应有 1 行
    assert table.rowCount() == 1, f"应 1 行，实际 {table.rowCount()}"
    # 首次出现 col 4
    first_seen = table.item(0, 4).text()
    last_seen = table.item(0, 5).text()
    # 容差：当前时间前后 2 秒
    for t_str in (first_seen, last_seen):
        assert now_before <= t_str <= now_after or t_str == now_before or t_str == now_after, (
            f"时间 '{t_str}' 不在 [{now_before}, {now_after}] 范围内")
    # 操作列有按钮
    cell = table.cellWidget(0, 7)
    assert cell is not None, "操作列无按钮容器"
    btns = cell.findChildren(QtWidgets.QPushButton)
    assert len(btns) == 3
    page.close()
    page.deleteLater()


def test_program_in_both_scan_and_log_uses_log_times():
    """在 scan 和 host_log 都存在 → 1 行，使用 host_log 时间。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\Both.exe"), "name": "Both",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 2, "blocked": False, "user_data_dirs": []}],
        host_log_data=[{
            "exe": _norm(r"C:\Apps\Both.exe"), "name": "Both",
            "first_seen": "2025-01-01 00:00:00",
            "last_seen": "2025-06-15 12:30:00",
            "status": "pending",
        }],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Both"  # 程序名
    assert table.item(0, 4).text() == "2025-01-01 00:00:00"  # 首次出现
    assert table.item(0, 5).text() == "2025-06-15 12:30:00"  # 最近出现
    assert table.item(0, 6).text() == "待处置"  # 处置状态
    page.close()
    page.deleteLater()


# ── Action column width test ───────────────────────────────────────────

def test_action_column_min_width():
    """操作列 min_width ≥ 3×56+间距（约 192px）。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[{
            "exe": _norm(r"C:\Apps\A.exe"), "name": "A",
            "first_seen": "2025-01-01 00:00:00",
            "last_seen": "2025-01-01 00:00:00",
            "status": "pending",
        }],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    # 操作列 = col 7
    action_col_width = table.columnWidth(7)
    assert action_col_width >= 192, (
        f"操作列宽 {action_col_width}px < 192px（3×56+间距）")
    page.close()
    page.deleteLater()


# ── Action buttons no overlap ──────────────────────────────────────────

def test_action_buttons_no_overlap_in_merged_table():
    """操作列中三个按钮不重叠。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[{
            "exe": _norm(r"C:\Apps\A.exe"), "name": "A",
            "first_seen": "2025-01-01 00:00:00",
            "last_seen": "2025-01-01 00:00:00",
            "status": "pending",
        }],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    cell = table.cellWidget(0, 7)
    assert cell is not None
    btns = cell.findChildren(QtWidgets.QPushButton)
    assert len(btns) == 3
    for i in range(3):
        for j in range(i + 1, 3):
            assert not btns[i].geometry().intersects(btns[j].geometry()), (
                f"{btns[i].text()} 与 {btns[j].text()} 重叠")
    page.close()
    page.deleteLater()


# ── Right-click menu: hide ─────────────────────────────────────────────

def test_hide_program_via_right_click_menu(monkeypatch):
    """右键「隐藏此程序」→ 程序从表中消失。"""
    import modules.webview_control.page as page_mod

    scan_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0,
         "blocked": False, "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
         "procs": [], "webview_count": 1, "connections": 0,
         "blocked": False, "user_data_dirs": []},
    ]
    mod, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert table.rowCount() == 2

    # 模拟右键隐藏 A
    from modules.webview_control.config import load_hidden_hosts, save_hidden_hosts
    hidden = load_hidden_hosts(mod.context.config)
    hidden.append(_norm(r"C:\Apps\A.exe"))
    save_hidden_hosts(mod.context.config, hidden)
    getattr(mod, "_page_refresh")()

    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()
    for _ in range(3):
        QApplication.processEvents()

    assert table.rowCount() == 1, f"隐藏 A 后应 1 行，实际 {table.rowCount()}"
    assert table.item(0, 0).text() == "B"
    page.close()
    page.deleteLater()


# ── Restore display dialog ─────────────────────────────────────────────

def test_restore_display_dialog():
    """恢复显示对话框可调用。"""
    from modules.webview_control.hidden_dialog import show_hidden_dialog
    _, QtCore, _, _ = import_qt()

    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
                    "procs": [], "webview_count": 1, "connections": 0,
                    "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    calls = []
    dlg = show_hidden_dialog(
        page, [_norm(r"C:\Apps\A.exe")], calls.append)
    lst = dlg._list
    assert lst.count() == 1
    lst.setCurrentRow(0)
    dlg._on_delete_pressed()
    assert calls == [_norm(r"C:\Apps\A.exe")]
    dlg.close()
    dlg.deleteLater()
    page.close()
    page.deleteLater()


# ── Filter dropdown preserved ──────────────────────────────────────────

def test_filter_dropdown_with_pending_entries():
    """处置状态下拉过滤仍正常工作：默认全部，切待处置只显示待处置条目。"""
    from qfluentwidgets import ComboBox

    mod, page = _make_page(
        scan_data=[],
        host_log_data=[
            {"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
             "first_seen": "2025-01-01", "last_seen": "2025-01-02", "status": "pending"},
            {"exe": _norm(r"C:\Apps\B.exe"), "name": "B",
             "first_seen": "2025-01-01", "last_seen": "2025-01-03", "status": "allowed"},
        ],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    combos = page.findChildren(ComboBox)
    assert len(combos) == 1, f"应只有一个过滤下拉，实际 {len(combos)}"
    combo = combos[0]
    assert combo.currentData() == "all"

    # 默认"全部"视图：A + B 都在（host_log 记录）
    # A 在扫描中不存在但有 host_log → 应显示在 merged table
    # B 的 status=allowed → 也在全部视图中
    # 扫描为空 → 无扫描行
    all_rows = table.rowCount()
    assert all_rows == 2, f"全部视图应显示 2 条，实际 {all_rows}"

    # 切"待处置" → 只有 A
    combo.setCurrentIndex(0)
    for _ in range(3):
        QApplication.processEvents()
    assert combo.currentData() == "pending"
    pending_rows = table.rowCount()
    assert pending_rows == 1, f"待处置视图应显示 1 条，实际 {pending_rows}"

    # 切"已处置"
    combo.setCurrentIndex(1)
    for _ in range(3):
        QApplication.processEvents()
    assert combo.currentData() == "done"

    # 切回"全部"
    combo.setCurrentIndex(2)
    for _ in range(3):
        QApplication.processEvents()
    assert combo.currentData() == "all"
    all_rows = table.rowCount()
    assert all_rows >= pending_rows, "全部视图应 ≥ pending 视图行数"

    page.close()
    page.deleteLater()


# ── Adaptive column widths ─────────────────────────────────────────────

def test_column_widths_sum_to_viewport():
    """自适应列宽：900px 下各列宽之和 == viewport 宽，无横向滚动条。"""
    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    total = sum(table.columnWidth(c) for c in range(table.columnCount()))
    assert total == table.viewport().width(), (
        f"列宽和 {total} != viewport 宽 {table.viewport().width()}")
    assert table.horizontalScrollBar().maximum() == 0, "出现横向滚动条"
    page.close()
    page.deleteLater()


def test_adaptive_filter_survives_gc_and_resize():
    """_AdaptiveFilter 不被 GC：gc.collect() 后 resize 仍触发自适应 reflow。"""
    import gc
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()

    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    gc.collect()
    page.resize(1400, 600)
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)
    total = sum(table.columnWidth(c) for c in range(table.columnCount()))
    assert total == table.viewport().width(), (
        f"gc 后 resize 1400: 列宽和 {total} != viewport 宽 {table.viewport().width()} "
        f"（_AdaptiveFilter 可能已被 GC）")
    assert table.horizontalScrollBar().maximum() == 0, "出现横向滚动条"
    page.close()
    page.deleteLater()


def test_no_zero_width_column_at_500px():
    """failure-path：500px 极窄窗口下列宽均 > 0（无 0 宽列）。"""
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()

    mod, page = _make_page(
        scan_data=[{"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
                    "running": True, "procs": [], "webview_count": 1,
                    "connections": 0, "blocked": False, "user_data_dirs": []}],
        host_log_data=[],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    page.resize(500, 600)
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)
    widths = [table.columnWidth(c) for c in range(table.columnCount())]
    assert all(w > 0 for w in widths), f"存在 0 宽列: {widths}"
    page.close()
    page.deleteLater()


# ── Smoke: subprocess isolation ────────────────────────────────────────

def test_webview_merged_smoke_subprocess():
    """Subprocess isolation: 合并表 760px 窄窗渲染 (icuuc.dll guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_webview_merged_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_webview_merged.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )
    assert "WEBVIEW_MERGED_OK" in result.stdout.decode(errors="replace")


def test_webview_merged_smoke_child():
    """Child: 合并表单表 8 列、操作按钮不重叠、过滤下拉存在。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from qfluentwidgets import ComboBox
    from modules.webview_control.module import Module

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

    mod = Module(_FakeContext(_FakeConfig()))
    mod.host_log = [{
        "exe": _norm(r"C:\Apps\A.exe"), "name": "A",
        "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
        "status": "pending",
    }]

    import modules.webview_control.page as page_mod
    page_mod.scan_hosts = lambda blocked: [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0,
         "blocked": False, "user_data_dirs": []},
    ]

    page = mod.create_page(None)
    page.resize(760, 600)
    page.show()
    for _ in range(5):
        app.processEvents()
        QtCore.QThread.msleep(20)

    # 1 QTableWidget, 8 cols
    tables = page.findChildren(QtWidgets.QTableWidget)
    assert len(tables) == 1, f"应 1 个表，实际 {len(tables)}"
    t = tables[0]
    assert t.columnCount() == 8

    # 过滤下拉
    combos = page.findChildren(ComboBox)
    assert len(combos) == 1
    assert combos[0].currentData() == "all"

    # 操作列按钮不重叠
    cell = t.cellWidget(0, 7)
    assert cell is not None, "操作列无按钮"
    btns = cell.findChildren(QtWidgets.QPushButton)
    assert len(btns) == 3
    for i in range(3):
        for j in range(i + 1, 3):
            assert not btns[i].geometry().intersects(btns[j].geometry()), (
                f"{btns[i].text()} 与 {btns[j].text()} 重叠")

    page.close()
    page.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("WEBVIEW_MERGED_OK")
