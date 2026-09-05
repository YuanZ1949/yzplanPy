"""模块页面窗口（无边框 RSS + 原生模块）离屏构建冒烟测试。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

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
    laid = [tb.buttonLayout.itemAt(i).widget() for i in range(tb.buttonLayout.count())]
    assert dlg.settingsBtn in laid
    assert dlg.moreBtn in laid
    assert tb.minBtn is not None
    assert tb.maxBtn is not None
    assert tb.closeBtn is not None
    assert dlg.minimumSize().width() == 940
    assert dlg.minimumSize().height() == 580
    # 内容区必须让出标题栏高度，避免与标题栏重叠
    assert dlg.layout().contentsMargins().top() == tb.height()

    dlg.settingsBtn.click()
    assert _StubPage.toggled == 1

    # 重复打开 = 同一个窗口（不会出现内容同步的第二个窗口）
    assert open_module_page(mod) is dlg
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
    assert isinstance(d1, QtWidgets.QDialog)

    # 从模块选项卡入口打开同一模块 → 仍是同一个窗口
    tab = ModulesTab(_FakeCtx())
    tab._open_page(reg.mod)
    assert open_module_page(reg.mod) is d1
    d1.hide()