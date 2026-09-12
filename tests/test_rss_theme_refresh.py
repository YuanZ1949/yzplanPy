"""RSS 页面主题切换动态刷新 QSS 回归测试（Task C: 主题切换动态刷新）。

覆盖：
(a) _apply_theme() 幂等重设工具栏/三栏/列表 QSS（不重建控件）；
(b) 深色/浅色切换后 QSS 颜色随之变化（动态刷新）；
(c) 状态胶囊在文字为空时不添加背景（避免构建期出现绿色药丸）。

UI 构建放在子进程（0xC0000005 崩溃隔离），父测试断言子进程退出码。
"""
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run_child(child_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_rss_theme_refresh.py::{child_name}", "-q"],
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


def test_theme_refresh_qss():
    """Subprocess isolation: 主题切换后 _apply_theme 重设 QSS。"""
    _run_child("test_theme_refresh_qss_child")


def test_theme_refresh_qss_child():
    """Child: 深色/浅色下 _apply_theme 重设 QSS 且颜色随主题变化（离屏）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile

    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import Theme, qconfig
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

    qconfig.theme = Theme.DARK
    page = m._RssPageWidget(_FakeOwner(store), None)
    page.show()
    try:
        app.processEvents()
        # (a) 构建期已应用一次主题 QSS
        qss_dark = page.tool_bar.styleSheet()
        assert "background:" in qss_dark, "工具栏 QSS 应含背景色"
        title_dark = page._summary_title.styleSheet()
        # 幂等：再次调用不改变 QSS
        page._apply_theme()
        assert page.tool_bar.styleSheet() == qss_dark, "_apply_theme 应幂等"
        # (c) 状态胶囊文字为空：不添加背景（避免构建期出现绿色药丸）
        assert "background:" not in page._summary_status.styleSheet(), (
            "空文字状态胶囊不应有背景色")
        # 切浅色：QSS 颜色随之变化（工具栏 + 摘要标题文字色）
        qconfig.theme = Theme.LIGHT
        page._apply_theme()
        qss_light = page.tool_bar.styleSheet()
        assert "background:" in qss_light
        title_light = page._summary_title.styleSheet()
        assert title_dark != title_light, "摘要标题 QSS 应随深浅主题变化"
        # 状态胶囊：设置文字后刷新出现背景色
        page._summary_status.setText("磁链")
        page._refresh_status_chip()
        assert "background:" in page._summary_status.styleSheet(), (
            "磁链胶囊应有背景色")
        # 控件仍存在（未重建）
        for attr in ("tool_bar", "_side_col", "_list_col", "_preview_col",
                     "item_list", "_summary_title", "_summary_meta",
                     "_summary_desc", "_preview_placeholder", "_globe",
                     "_lbl_title", "lb_page", "lb_total", "_sep_line",
                     "_grip1", "_grip2"):
            assert hasattr(page, attr), f"页面缺少 {attr}"
    finally:
        page.close()
        page.deleteLater()