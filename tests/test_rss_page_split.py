"""RSS 页面三栏构建拆分回归测试（Task C: 拆分 page 三栏构建）。

覆盖：
(a) _build_ui / _build_tool_bar / _build_three_col / _make_grip / _apply_theme
    定义在 modules.rss_aggregator.page_layout（page.py 仅保留控制器）；
(b) 页面实例包含三栏（侧栏/列表/预览）、两个拖拽手柄、工具栏与搜索框。

UI 构建放在子进程（0xC0000005 崩溃隔离），父测试断言子进程退出码。
"""
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run_child(child_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_rss_page_split.py::{child_name}", "-q"],
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


def test_page_layout_split():
    """Subprocess isolation: 三栏构建函数位于 page_layout，页面实例结构完整。"""
    _run_child("test_page_layout_split_child")


def test_page_layout_split_child():
    """Child: 构建 RSS 页面，验证构建函数归属与三栏结构（离屏）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile

    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
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
    try:
        app.processEvents()
        # (a) 构建函数定义在 page_layout
        for name in ("_build_ui", "_build_tool_bar", "_build_three_col",
                     "_make_grip", "_apply_theme"):
            fn = getattr(m._RssPageWidget, name)
            assert fn.__module__ == "modules.rss_aggregator.page_layout", (
                f"{name} 应定义在 page_layout, 实际 {fn.__module__}")
        # (b) 三栏 + 拖拽手柄 + 工具栏 + 搜索框
        for attr in ("tool_bar", "_side_col", "_list_col", "_preview_col",
                     "_grip1", "_grip2", "item_list", "search_input",
                     "btn_date_filter", "btn_filter", "btn_read_ops",
                     "btn_batch_ops", "btn_thumb"):
            assert hasattr(page, attr), f"页面缺少 {attr}"
        assert page._grip1._index == 1 and page._grip2._index == 2, (
            "拖拽手柄 index 应为 1/2")
        assert page._side_col.width() >= 0 and page._list_col.width() >= 0
    finally:
        page.close()
        page.deleteLater()