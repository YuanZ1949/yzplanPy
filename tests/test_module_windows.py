"""模块窗口独立化：任务栏独立条目 + 最大化/最小化 + 不强制在主窗口上方。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from ui.module_pages import _ModulePageWindow, _ModuleWindow, close_module_pages, open_module_page


class _NativeMod:
    name = "测试模块"
    id = "native_win_test"
    description = "desc"

    def __init__(self):
        self.page = None

    def create_page(self, _parent):
        self.page = QtWidgets.QWidget()
        return self.page


def test_module_window_is_independent_top_level():
    # 普通模块窗口：无父、顶层、非模态、含最小化/最大化按钮
    mod = _NativeMod()
    win = open_module_page(mod)
    try:
        assert isinstance(win, _ModulePageWindow)
        assert win.parent() is None, "独立顶层窗口不应有父窗口"
        assert win.windowFlags() & QtCore.Qt.Window
        assert win.windowFlags() & QtCore.Qt.WindowMinMaxButtonsHint, "应含最小化/最大化按钮"
        assert win.windowFlags() & QtCore.Qt.WindowSystemMenuHint
        assert win.windowFlags() & QtCore.Qt.WindowTitleHint
        assert win.windowFlags() & QtCore.Qt.WindowCloseButtonHint, "原生标题栏应含可点击的关闭按钮"
        assert win.windowModality() == QtCore.Qt.NonModal, "应保持非模态"
        assert win.windowTitle() == "测试模块"
        assert win.minimumSize().width() == 760
        assert win.minimumSize().height() == 560
        assert win.testAttribute(QtCore.Qt.WA_DeleteOnClose)
    finally:
        win.hide()


def test_module_window_singleton_and_close_clears_pages():
    # 单例：重复打开返回同一窗口；关闭后 _pages 清空
    mod = _NativeMod()
    w1 = open_module_page(mod)
    try:
        assert open_module_page(mod) is w1
    finally:
        w1.hide()
    w1.close()
    QtWidgets.QApplication.processEvents()
    from ui.module_pages import _pages
    assert mod.id not in _pages, "窗口关闭后单例表应移除该模块"


def test_close_module_pages_closes_all():
    # 主窗口退出时遍历关闭所有独立模块窗口
    mod_a = _NativeMod()
    mod_a.id = "native_win_a"
    mod_b = _NativeMod()
    mod_b.id = "native_win_b"
    wa = open_module_page(mod_a)
    wb = open_module_page(mod_b)
    try:
        from ui.module_pages import _pages
        assert mod_a.id in _pages and mod_b.id in _pages
        close_module_pages()
        QtWidgets.QApplication.processEvents()
        assert mod_a.id not in _pages and mod_b.id not in _pages, "close_module_pages 后单例表应清空"
    finally:
        for w in (wa, wb):
            if w is not None:
                try:
                    w.hide()
                except RuntimeError:
                    pass  # WA_DeleteOnClose 已销毁


class _FramelessMod:
    """带 frameless=True 页面的模块 → 走 _ModuleWindow（FluentTitleBar 无边框窗）。"""

    name = "测试模块"
    id = "frameless_win_test"
    description = "desc"

    def __init__(self):
        self.page = None

    def create_page(self, _parent):
        self.page = QtWidgets.QWidget()
        self.page.frameless = True
        return self.page


def _simulate_altf4(win):
    """复刻 qfluentwidgets AcrylicWindow.nativeEvent 的 Alt+F4 路径：
    置 __closedByKey=True 后直接 sendEvent 一个原始 QCloseEvent
    （绕过 QWidget.close() 的 hide+delete 逻辑）。"""
    win._AcrylicWindow__closedByKey = True
    QtWidgets.QApplication.sendEvent(win, QtGui.QCloseEvent())
    QtWidgets.QApplication.processEvents()


def test_frameless_module_window_altf4_closes_not_hides():
    # Alt+F4 必须真正关闭（而非被 AcrylicWindow 隐藏），且 _pages 清理干净
    mod = _FramelessMod()
    win = open_module_page(mod)
    try:
        assert isinstance(win, _ModuleWindow)
        assert win.isVisible()
        _simulate_altf4(win)
        from ui.module_pages import _pages
        assert mod.id not in _pages, "Alt+F4 后单例表应移除该模块（不得隐藏泄漏）"
    finally:
        try:
            win.hide()
        except RuntimeError:
            pass


def test_frameless_module_window_reopen_after_altf4_no_leak():
    # Alt+F4 关闭后重新打开：新窗口入表，旧窗口已销毁，_pages 仅 1 条
    mod = _FramelessMod()
    win = open_module_page(mod)
    _simulate_altf4(win)
    from ui.module_pages import _pages
    assert mod.id not in _pages
    win2 = open_module_page(mod)
    try:
        assert win2 is not win
        assert mod.id in _pages
        assert len(_pages) == 1, "不得残留隐藏的旧窗口"
    finally:
        try:
            win2.hide()
        except RuntimeError:
            pass


def test_frameless_module_window_x_button_closes():
    # ✕ 路径（window().close()）正常关闭并清理 _pages
    mod = _FramelessMod()
    win = open_module_page(mod)
    try:
        assert isinstance(win, _ModuleWindow)
        win.close()
        QtWidgets.QApplication.processEvents()
        from ui.module_pages import _pages
        assert mod.id not in _pages, "✕ 关闭后单例表应移除该模块"
    finally:
        try:
            win.hide()
        except RuntimeError:
            pass