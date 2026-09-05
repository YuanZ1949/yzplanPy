"""回归：QtWebEngine 必须保持惰性加载。

在离屏模式下加载主要模块（含 RSS 聚合、页面选择器），断言
PySide6.QtWebEngine* 不会因此进入 sys.modules——避免启动期即拉起
Chromium 线程池（本机一次性产生 ~70-90 个常驻空闲原生线程）。
仅在首次创建预览/选择器视图时才允许加载这些模块。
参见 开发日志 2026-09-05。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

import modules.rss_aggregator as rss_aggregator
import modules.page_selector as page_selector
import modules.rss_store as rss_store

_WEBENGINE_MODULES = (
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
)


def test_webengine_not_imported_after_modules_load():
    for name in _WEBENGINE_MODULES:
        assert name not in sys.modules, f"{name} 不应在启动期被导入"


def test_page_selector_import_has_no_webengine_side_effect():
    # 回归：page_selector.py 的 WebEngine 导入已改为惰性（此前为模块级导入）
    for name in _WEBENGINE_MODULES:
        assert name not in sys.modules


def test_webengine_still_available_lazily():
    # 惰性 getter 在真正需要时应能拿到 QWebEngineView（不因重构而失效）
    assert page_selector._webengine_view() is not None
    assert "PySide6.QtWebEngineWidgets" in sys.modules