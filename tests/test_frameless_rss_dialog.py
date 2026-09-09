"""模块页面窗口（无边框 RSS + 原生模块）离屏构建冒烟测试。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from qfluentwidgets import FluentIcon, ToolButton
from qfluentwidgets.components.widgets.frameless_window import FramelessWindow
from ui.module_pages import open_module_page
from ui.modules_tab import ModulesTab


class _StubPage(QtWidgets.QWidget):
    """带标题栏所需回调的 RSS 页面替身。"""

    frameless = True
    toggled = 0

    def _toggle_settings_section(self):
        type(self).toggled += 1


class _RssMod:
    name = "RSS 订阅"
    id = "rss_aggregator"

    def create_page(self, _parent):
        return _StubPage()


def test_frameless_rss_dialog_builds_and_singleton():
    mod = _RssMod()
    dlg = open_module_page(mod)
    assert isinstance(dlg, FramelessWindow)

    tb = dlg.titleBar
    laid = [tb.buttonLayout.itemAt(i).widget() for i in range(tb.buttonLayout.count())]  # type: ignore[reportAttributeAccessIssue]
    assert dlg.settingsBtn in laid  # type: ignore[reportAttributeAccessIssue]
    assert dlg.moreBtn in laid  # type: ignore[reportAttributeAccessIssue]
    assert tb.minBtn is not None
    assert tb.maxBtn is not None
    assert tb.closeBtn is not None
    assert dlg.minimumSize().width() == 940
    assert dlg.minimumSize().height() == 580
    # 内容区必须让出标题栏高度，避免与标题栏重叠
    lay = dlg.layout()
    assert lay is not None
    assert lay.contentsMargins().top() == tb.height()

    dlg.settingsBtn.click()  # type: ignore[reportAttributeAccessIssue]
    assert _StubPage.toggled == 1

    # 重复打开 = 同一个窗口（不会出现内容同步的第二个窗口）
    assert open_module_page(mod) is dlg
    dlg.hide()


class _StubPageCustom(_StubPage):
    """带 title_bar_spec 的 RSS 页面替身（T7 自定义标题栏路径）。"""

    def __init__(self):
        super().__init__()
        self._calls = []

    def _toggle_settings_section(self):
        super()._toggle_settings_section()
        self._calls.append("settings")

    def _do_export(self):
        self._calls.append("export")

    def _do_import(self):
        self._calls.append("import")

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


def test_rss_custom_title_bar_three_buttons():
    """T7: 页面带 title_bar_spec 时走自定义标题栏——three ToolButton 文字准确、moreBtn 消失、窗口控制保留。"""

    class Mod:
        name = "RSS 订阅"
        id = "rss_custom_t9"  # 独立 id，避免与既有单例测试共用窗口

        def create_page(self, _parent):
            return _StubPageCustom()

    mod = Mod()
    dlg = open_module_page(mod)
    try:
        assert isinstance(dlg, FramelessWindow)
        # custom 路径：不再创建 settingsBtn/moreBtn
        assert not hasattr(dlg, "settingsBtn")
        assert not hasattr(dlg, "moreBtn")
        tb = dlg.titleBar
        btns = [b for b in tb.findChildren(ToolButton) if b.text()]
        assert {b.text() for b in btns} == {"设置", "导出", "导入"}
        # 窗口控制按钮保留
        assert tb.minBtn is not None
        assert tb.maxBtn is not None
        assert tb.closeBtn is not None
        # 点击三按钮 → 各自回调触发
        for b in btns:
            b.click()
        assert dlg._page._calls == ["settings", "export", "import"]  # type: ignore[reportAttributeAccessIssue]
        assert _StubPage.toggled == 1
        # --- 布局断言 ---
        for b in btns:
            assert b.width() >= 96, f"按钮 '{b.text()}' 宽度 {b.width()} < 96"
        assert tb.buttonLayout.spacing() == 4
        by_x = sorted(btns, key=lambda b: b.x())
        for i in range(len(by_x) - 1):
            b1, b2 = by_x[i], by_x[i + 1]
            assert b2.x() >= b1.x() + b1.width() + 4, (
                f"相邻按钮重叠: '{b1.text()}' 右边界 {b1.x() + b1.width()} > '{b2.text()}' x={b2.x()}"
            )
    finally:
        assert dlg is not None
        dlg.hide()


class _NativeMod:
    name = "测试模块"
    id = "native_test"
    description = "desc"

    def __init__(self):
        self.page = None

    def create_page(self, _parent):
        self.page = QtWidgets.QWidget()
        return self.page


class _FakeReg:
    def __init__(self):
        self.mod = _NativeMod()

    def all(self):
        return [self.mod]

    def is_enabled(self, _i):
        return True


class _FakeCtx:
    def __init__(self):
        self.registry = _FakeReg()


def test_native_module_singleton_across_entries():
    """托盘与模块选项卡共用单例：原生模块也不会出现重复窗口。"""
    reg = _FakeReg()
    d1 = open_module_page(reg.mod)
    assert isinstance(d1, QtWidgets.QWidget)
    assert d1.parent() is None
    assert d1.windowFlags() & QtCore.Qt.Window
    assert d1.windowModality() == QtCore.Qt.NonModal

    # 从模块选项卡入口打开同一模块 → 仍是同一个窗口
    tab = ModulesTab(_FakeCtx())
    tab._open_page(reg.mod)
    assert open_module_page(reg.mod) is d1
    assert d1 is not None
    d1.hide()