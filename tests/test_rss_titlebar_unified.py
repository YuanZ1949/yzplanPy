"""RSS 模块标题栏统一化回归测试（Task: RSS 标题栏统一紧凑规格）。

覆盖：
(a) 模块窗口 spec 按钮为 _TextTitleBarButton，宽=14+6+文字宽+16、高 28（不截断、紧凑）；
(b) spec 按钮 styleSheet 为空（无浅色弹片背景，主题自适应绘制）；
(c) 迁移进标题栏的 5 个按钮为紧凑透明 QSS（无浅色弹片、无边框、主题文字色）；
(d) 标题栏高度与主窗口 FluentTitleBar 默认统一（48px），内容区让出同高。

UI 构建放在子进程（0xC0000005 崩溃隔离），父测试断言子进程退出码。
"""
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run_child(child_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_rss_titlebar_unified.py::{child_name}", "-q"],
        timeout=120,
        capture_output=True,
        cwd=str(_ROOT),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


def test_module_window_titlebar_unified():
    """Subprocess isolation: 模块窗口 spec 按钮紧凑规格 + 高度统一 48px。"""
    _run_child("test_module_window_titlebar_unified_child")


def test_migrated_buttons_compact_qss():
    """Subprocess isolation: 迁移按钮紧凑透明 QSS（无浅色弹片）。"""
    _run_child("test_migrated_buttons_compact_qss_child")


def test_module_window_titlebar_unified_child():
    """Child: 构建带 title_bar_spec 的模块窗口，验证标题栏统一规格（离屏）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import FluentIcon
    from ui.module_pages import open_module_page
    from ui.title_bar_kit import _TextTitleBarButton

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    class _StubPage(QtWidgets.QWidget):
        frameless = True

        def _toggle_settings_section(self):
            pass

        def _do_export(self):
            pass

        def _do_import(self):
            pass

        @property
        def title_bar_spec(self):
            return {"buttons": [
                {"icon": FluentIcon.SETTING, "text": "设置", "tooltip": "模块设置",
                 "cb": self._toggle_settings_section},
                {"icon": FluentIcon.SHARE, "text": "导出", "tooltip": "导出 OPML",
                 "cb": self._do_export},
                {"icon": FluentIcon.FOLDER, "text": "导入", "tooltip": "导入 OPML",
                 "cb": self._do_import},
            ]}

    class _Mod:
        name = "RSS 订阅"
        id = "rss_titlebar_unified"

        def create_page(self, _parent):
            return _StubPage()

    dlg = open_module_page(_Mod())
    assert dlg is not None
    try:
        app.processEvents()
        tb = dlg.titleBar
        # (d) 高度统一：与主窗口 FluentTitleBar 默认一致（48px），内容区让出同高
        assert tb.height() == 48, f"标题栏高度应为 48, 实际 {tb.height()}"
        lay = dlg.layout()
        assert lay is not None
        assert lay.contentsMargins().top() == tb.height(), (
            "内容区顶部边距应与标题栏高度一致")
        # (a) spec 按钮为 _TextTitleBarButton，紧凑规格：宽=14+6+文字+16、高 28
        btns = [b for b in tb.findChildren(_TextTitleBarButton) if b._text]
        assert {b._text for b in btns} == {"设置", "导出", "导入"}
        for b in btns:
            assert b.height() == 28, f"按钮 '{b._text}' 高度应为 28, 实际 {b.height()}"
            tw = QtGui.QFontMetrics(_TextTitleBarButton._FONT).horizontalAdvance(b._text)
            expect_w = 14 + 6 + tw + 16
            assert b.sizeHint().width() == expect_w, (
                f"按钮 '{b._text}' sizeHint 宽 {b.sizeHint().width()} != {expect_w}")
            assert b.width() == expect_w, (
                f"按钮 '{b._text}' 实际宽 {b.width()} != {expect_w}（内容被截断）")
            # (b) 无浅色弹片背景：styleSheet 为空（主题自适应绘制）
            assert b.styleSheet() == "", f"按钮 '{b._text}' 不应有 QSS 弹片背景"
    finally:
        dlg.hide()
        dlg.close()


def test_migrated_buttons_compact_qss_child():
    """Child: 真实 RSS 页面迁移后 5 个按钮为紧凑透明 QSS（无浅色弹片）。"""
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

    def _fake_fluent_title_bar():
        """忠实模拟 FluentTitleBar 布局：hBoxLayout=[icon, title, stretch, vBoxLayout]。"""
        tb = QtWidgets.QWidget()
        tb.hBoxLayout = QtWidgets.QHBoxLayout(tb)
        tb.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        tb.iconLabel = QtWidgets.QLabel("◎", tb)
        tb.titleLabel = QtWidgets.QLabel("RSS 聚合", tb)
        tb.hBoxLayout.addWidget(tb.iconLabel)
        tb.hBoxLayout.addWidget(tb.titleLabel)
        tb.hBoxLayout.addStretch(1)
        tb.vBoxLayout = QtWidgets.QVBoxLayout()
        tb.buttonLayout = QtWidgets.QHBoxLayout()
        tb.buttonLayout.setContentsMargins(0, 0, 0, 0)
        for _ in range(3):  # min / max / close 窗口按钮占位
            tb.buttonLayout.addWidget(QtWidgets.QPushButton("□", tb))
        tb.vBoxLayout.addLayout(tb.buttonLayout)
        tb.hBoxLayout.addLayout(tb.vBoxLayout)
        tb.show()
        return tb

    page = m._RssPageWidget(_FakeOwner(store), None)
    page.show()
    tb = _fake_fluent_title_bar()
    try:
        page._build_title_bar_widgets(tb)
        # (c) 5 个迁移按钮：紧凑透明 QSS（无浅色弹片、无边框、主题文字色）+ 28px 高
        for b in (page.btn_date_filter, page.btn_filter, page.btn_read_ops,
                  page.btn_batch_ops, page.btn_thumb):
            qss = b.styleSheet()
            assert "background: transparent" in qss, f"{b.text()}: 应有透明背景"
            assert "border: none" in qss, f"{b.text()}: 应无边框"
            assert "color:" in qss, f"{b.text()}: 应有主题文字色"
            assert "rgba(255,255,255,0.09)" not in qss, f"{b.text()}: 不应有浅色弹片背景"
            assert b.minimumHeight() == 28 and b.maximumHeight() == 28, (
                f"{b.text()}: 高度应为 28")
    finally:
        tb.close()
        tb.deleteLater()
        page.close()
        page.deleteLater()