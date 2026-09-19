"""webview_control 拦截记录视图过滤：默认显示全部(all)条目。

覆盖 Task 3：_pending_entries 纯函数（pending/done/all 三视图 + 空列表 +
缺 status 键条目视为非 pending）；子进程冒烟 760px 窄窗渲染——默认显示全部
3 条、切"已处置"显示 B+C、切"待处置"只显示 A、处置 A 后待处置视图消失、
切"全部"三条仍在（host_log 记录未被删除）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139）。
from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

from modules.webview_control.page import _pending_entries

QApplication = QtWidgets.QApplication


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _three_entries():
    return [
        {"exe": r"C:\Apps\A.exe", "name": "A", "status": "pending"},
        {"exe": r"C:\Apps\B.exe", "name": "B", "status": "allowed"},
        {"exe": r"C:\Apps\C.exe", "name": "C", "status": "blocked"},
    ]


def test_pending_entries_pending_view_only_pending():
    got = _pending_entries(_three_entries(), "pending")
    assert [e["name"] for e in got] == ["A"]


def test_pending_entries_done_view_excludes_pending():
    got = _pending_entries(_three_entries(), "done")
    assert sorted(e["name"] for e in got) == ["B", "C"]


def test_pending_entries_all_view_keeps_order():
    entries = _three_entries()
    got = _pending_entries(entries, "all")
    assert got == entries
    assert [e["name"] for e in got] == ["A", "B", "C"]


def test_pending_entries_empty_and_missing_status():
    assert _pending_entries([], "pending") == []
    assert _pending_entries([], "done") == []
    assert _pending_entries([], "all") == []
    # 缺 status 键的条目视为非 pending → 归入 done
    no_status = [{"exe": r"C:\Apps\X.exe", "name": "X"}]
    assert _pending_entries(no_status, "pending") == []
    assert _pending_entries(no_status, "done") == no_status


def test_webview_pending_smoke_subprocess():
    """Subprocess isolation: 默认全部视图 + 待处置过滤 (icuuc.dll guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_webview_pending_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_webview_pending.py::{child_name}",
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
    assert "WEBVIEW_PENDING_OK" in result.stdout.decode()


def test_webview_pending_smoke_child(monkeypatch):
    """Child: 默认显示全部，处置后从待处置视图消失，可切换回看。"""
    import os
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

    monkeypatch.setattr("modules.webview_control.page.scan_hosts", lambda blocked: [])

    mod = Module(_FakeContext(_FakeConfig()))
    mod.host_log = [
        {"exe": r"C:\Apps\A.exe", "name": "A",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
         "status": "pending"},
        {"exe": r"C:\Apps\B.exe", "name": "B",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-03 00:00:00",
         "status": "allowed"},
        {"exe": r"C:\Apps\C.exe", "name": "C",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-04 00:00:00",
         "status": "blocked"},
    ]
    page = mod.create_page(None)
    page.resize(760, 600)
    page.show()
    # 自适应列宽经 singleShot 延迟 reflow，需多轮事件循环落定
    for _ in range(5):
        app.processEvents()
        QtCore.QThread.msleep(20)

    log_tables = [t for t in page.findChildren(QtWidgets.QTableWidget)
                  if t.columnCount() == 8]
    assert log_tables, "未找到合并表"
    log_table = log_tables[0]

    combos = page.findChildren(ComboBox)
    assert len(combos) == 1, f"应只有一个视图过滤下拉，实际 {len(combos)}"
    combo = combos[0]
    assert combo.currentIndex() == 2, "默认应选中全部"
    assert combo.currentData() == "all"

    # 默认视图：显示全部 3 条
    assert log_table.rowCount() == 3, f"默认应显示全部 3 条，实际 {log_table.rowCount()}"
    assert log_table.item(0, 0).text() == "A"

    # 切"已处置" → B + C
    combo.setCurrentIndex(1)
    for _ in range(3):
        app.processEvents()
    assert combo.currentData() == "done"
    assert log_table.rowCount() == 2, f"已处置应显示 2 条，实际 {log_table.rowCount()}"

    # 切回"待处置" → 1
    combo.setCurrentIndex(0)
    for _ in range(3):
        app.processEvents()
    assert log_table.rowCount() == 1, f"切回待处置应显示 1 条，实际 {log_table.rowCount()}"

    # 模拟处置：A 放行后从待处置视图消失
    mod.host_log[0]["status"] = "allowed"
    getattr(mod, "_page_refresh")()
    for _ in range(3):
        app.processEvents()
    assert log_table.rowCount() == 0, f"处置后待处置视图应无条目，实际 {log_table.rowCount()}"

    # 切"全部" → 3 条都在（host_log 记录未被删除）
    combo.setCurrentIndex(2)
    for _ in range(3):
        app.processEvents()
    assert combo.currentData() == "all"
    assert log_table.rowCount() == 3, f"全部视图应显示 3 条，实际 {log_table.rowCount()}"
    assert len(mod.host_log) == 3, "host_log 记录不应被删除"

    page.close()
    page.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("WEBVIEW_PENDING_OK")