"""RSS 页面快捷键输入守卫回归测试（Task C: 快捷键输入守卫）。

覆盖：
(a) 搜索框（文本输入）聚焦时按 J 不移动列表选中行（快捷键让位给输入）；
(b) 列表聚焦时按 J 正常下移选中行。

UI 构建放在子进程（0xC0000005 崩溃隔离），父测试断言子进程退出码。
"""
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run_child(child_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_rss_key_guard.py::{child_name}", "-q"],
        timeout=120,
        capture_output=True,
        cwd=str(_ROOT),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )


def test_key_guard_text_input():
    """Subprocess isolation: 文本输入聚焦时 J 不触发列表快捷键。"""
    _run_child("test_key_guard_text_input_child")


def test_key_guard_text_input_child():
    """Child: 搜索框聚焦 J 被守卫，列表聚焦 J 正常移动（离屏）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile

    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from PySide6.QtTest import QTest
    from modules import rss_aggregator as m
    from modules.rss_store import RssStore

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))

    class _FakeConfig(dict):
        def __init__(self):
            super().__init__()
            self._data = {}

        def get(self, key, default=None):
            dct = {**self._data, **dict(self)}
            return dct.get(key, default)

        def set(self, key, value):
            self._data[key] = value

        def unset(self, key):
            self._data.pop(key, None)

    class _FakeCtx:
        def __init__(self):
            self.config = _FakeConfig()

    class _FakeOwner:
        def __init__(self, store):
            self.store = store
            self.context = _FakeCtx()

        def scan_hashes(self, limit=200):
            pass

        def refresh_favicons(self):
            pass

        def refresh_now(self):
            pass

    page = m._RssPageWidget(_FakeOwner(store), None)
    page.show()
    page.activateWindow()
    try:
        app.processEvents()
        page.item_list.addItem("条目 A")
        page.item_list.addItem("条目 B")
        page.item_list.setCurrentRow(0)
        app.processEvents()

        # (a) 搜索框聚焦：J 被守卫，选中行不变
        page.search_input.setFocus()
        app.processEvents()
        assert QtWidgets.QApplication.focusWidget() is page.search_input, (
            "搜索框应获得焦点")
        QTest.keyClick(page, QtCore.Qt.Key_J)
        app.processEvents()
        assert page.item_list.currentRow() == 0, (
            "搜索框聚焦时 J 不应移动列表选中行")

        # (b) 列表聚焦：J 正常下移
        page.item_list.setFocus()
        app.processEvents()
        QTest.keyClick(page, QtCore.Qt.Key_J)
        app.processEvents()
        assert page.item_list.currentRow() == 1, (
            "列表聚焦时 J 应下移选中行")
    finally:
        page.close()
        page.deleteLater()