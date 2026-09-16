"""RSS 侧栏 favicon 解码缓存：二次 reload 不重复解码、icon 变化失效、条数上限。"""
import importlib.util
import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _load_sidebar_data_synthetic():
    """合成包直接加载 sidebar_data.py（绕过 rss_aggregator/__init__.py）。

    并行单元正在重构 dialogs_*.py → dialogs/ 子包，__init__.py 可能暂不可导入；
    sidebar_data 依赖的 .sidebar/.text_utils/.utils 均为包内相对导入，不依赖 __init__ 导出。
    """
    pkg = types.ModuleType("modules.rss_aggregator")
    pkg.__path__ = [os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "modules", "rss_aggregator"))]
    sys.modules["modules.rss_aggregator"] = pkg
    spec = importlib.util.spec_from_file_location(
        "modules.rss_aggregator.sidebar_data",
        os.path.join(pkg.__path__[0], "sidebar_data.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["modules.rss_aggregator.sidebar_data"] = mod
    spec.loader.exec_module(mod)
    return mod


try:
    from modules.rss_aggregator import sidebar_data
    _PACKAGE_OK = True
except Exception:
    _PACKAGE_OK = False
    sidebar_data = _load_sidebar_data_synthetic()


def _png_b64(color):
    """用 Qt 生成一张 1x1 纯色 PNG 的 base64（保证是合法可解码图片）。"""
    img = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor(color))
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data().toBase64()).decode()


@pytest.fixture(autouse=True)
def _icon_cache_cleanup():
    sidebar_data._ICON_CACHE.clear()
    yield
    sidebar_data._ICON_CACHE.clear()
    if not _PACKAGE_OK:
        return
    from modules.rss_aggregator import _RssPageWidget
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for widget in list(app.allWidgets()):
        if isinstance(widget, _RssPageWidget):
            widget.close()
            widget.deleteLater()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, 0)


def _counting_decode(monkeypatch):
    """monkeypatch _decode_feed_icon 为计数包装，返回 calls 列表。"""
    calls = []
    orig = sidebar_data._decode_feed_icon

    def counting(data):
        calls.append(data)
        return orig(data)

    monkeypatch.setattr(sidebar_data, "_decode_feed_icon", counting)
    return calls


# ── 缓存函数：命中 / 失效 / 空图标 / 上限 ─────────────────────

def test_cached_feed_icon_second_call_no_decode(monkeypatch):
    calls = _counting_decode(monkeypatch)
    icon_data = _png_b64("#ff0000")

    ic1 = sidebar_data._cached_feed_icon(1, icon_data)
    ic2 = sidebar_data._cached_feed_icon(1, icon_data)

    assert ic1 is not None and not ic1.isNull()
    assert ic2 is ic1  # 命中缓存：同一 QIcon 实例
    assert len(calls) == 1  # 第二次不再解码


def test_cached_feed_icon_invalidates_on_change(monkeypatch):
    calls = _counting_decode(monkeypatch)
    icon_a = _png_b64("#ff0000")
    icon_b = _png_b64("#00ff00")

    ic1 = sidebar_data._cached_feed_icon(1, icon_a)
    ic2 = sidebar_data._cached_feed_icon(1, icon_b)

    assert len(calls) == 2  # icon 数据变化 → 缓存失效重新解码
    assert ic2 is not ic1
    # 缓存只存最新一份：回到旧 icon 也重新解码
    sidebar_data._cached_feed_icon(1, icon_a)
    assert len(calls) == 3


def test_cached_feed_icon_empty_not_cached(monkeypatch):
    calls = _counting_decode(monkeypatch)

    assert sidebar_data._cached_feed_icon(1, "") is None
    assert sidebar_data._cached_feed_icon(1, None) is None
    assert len(calls) == 0  # 空 icon 不触发解码
    assert 1 not in sidebar_data._ICON_CACHE


def test_cached_feed_icon_cap(monkeypatch):
    _counting_decode(monkeypatch)
    icon_data = _png_b64("#ff0000")

    n = sidebar_data._ICON_CACHE_MAX + 50
    for i in range(n):
        sidebar_data._cached_feed_icon(i, icon_data)

    assert len(sidebar_data._ICON_CACHE) <= sidebar_data._ICON_CACHE_MAX
    assert len(sidebar_data._ICON_CACHE) > 0  # 超限清空后仍继续缓存