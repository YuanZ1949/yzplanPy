"""RSS 三栏宽度记忆测试：拖拽释放保存比例、重建页面恢复、释放事件接线。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from modules import rss_aggregator as m
from modules.rss_store import RssStore


class FakeConfig:
    """扁平 dot-path 键的配置替身（与 test_rss_sidebar.FakeConfig 一致）。"""

    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()


class FakeOwner:
    def __init__(self, store):
        self.store = store
        self.context = FakeCtx()


@pytest.fixture(autouse=True)
def _page_cleanup():
    yield
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for widget in list(app.allWidgets()):
        if isinstance(widget, m._RssPageWidget):
            widget.close()
            widget.deleteLater()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, 0)


def _make_page(owner):
    page = m._RssPageWidget(owner, None)
    return page


def test_drag_release_saves_col_widths(tmp_path):
    """拖拽结束（释放手柄）应把三栏宽度以比例为 key 写入配置。"""
    store = RssStore(str(tmp_path / "s.db"))
    owner = FakeOwner(store)
    page = _make_page(owner)

    # 模拟拖拽结束后的宽度状态（列表 500 / 预览 250 / 侧栏 250）
    page._side_width = 250
    page._list_width = 500
    page._preview_width = 250
    page._apply_sizes()
    page._save_col_widths()

    saved = owner.context.config.get("rss.col_widths")
    assert saved is not None
    total = saved["side"] + saved["list"] + saved["preview"]
    assert abs(total - 1.0) < 0.01
    assert abs(saved["side"] - 0.25) < 0.01
    assert abs(saved["list"] - 0.5) < 0.01
    assert abs(saved["preview"] - 0.25) < 0.01


def test_rebuild_restores_col_widths(tmp_path):
    """再次构建页面时应按上次保存的比例恢复三栏宽度（基准 1200，resizeEvent 再等比修正）。"""
    store = RssStore(str(tmp_path / "s.db"))
    owner = FakeOwner(store)
    owner.context.config.set("rss.col_widths",
                             {"side": 0.25, "list": 0.5, "preview": 0.25})
    page = _make_page(owner)

    assert page._side_width == 300      # 0.25 * 1200
    assert page._list_width == 600      # 0.5  * 1200
    assert page._preview_width == 300   # 0.25 * 1200


def test_rebuild_no_saved_widths_keeps_auto(tmp_path):
    """没有保存过宽度时，三栏保持自动分配（None），不写配置。"""
    store = RssStore(str(tmp_path / "s.db"))
    owner = FakeOwner(store)
    page = _make_page(owner)
    assert page._side_width is None
    assert page._list_width is None
    assert page._preview_width is None
    assert owner.context.config.get("rss.col_widths") is None


def test_rebuild_ignores_malformed_saved(tmp_path):
    """配置里的宽度数据非法（负数/非数字/缺键）时安全回退为自动分配。"""
    store = RssStore(str(tmp_path / "s.db"))
    owner = FakeOwner(store)
    owner.context.config.set("rss.col_widths", {"side": -5, "list": "x"})
    page = _make_page(owner)
    assert page._side_width is None
    assert page._list_width is None
    assert page._preview_width is None


def test_grip_release_triggers_save(tmp_path):
    """_DragGrip.mouseReleaseEvent 必须在拖拽结束时调用 _save_col_widths。"""
    store = RssStore(str(tmp_path / "s.db"))
    owner = FakeOwner(store)
    page = _make_page(owner)

    calls = []
    page._save_col_widths = lambda: calls.append(1)  # 记录接线点

    grip = page._make_grip(1)
    grip._dragging = True
    grip._page._drag_active = True
    ev = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease,
                           QtCore.QPointF(0, 0),
                           QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                           QtCore.Qt.NoModifier)
    grip.mouseReleaseEvent(ev)
    assert calls == [1], "释放手柄后未调用 _save_col_widths"