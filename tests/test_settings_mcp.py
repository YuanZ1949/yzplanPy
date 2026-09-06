import sys
import threading
import time

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


class _Cfg:
    def get(self, key, default=None):
        return default


class _Ctx:
    config = _Cfg()


def test_mcp_test_button_only_touches_gui_on_main_thread():
    # 回归：_test_mcp 后台线程不得直接创建/操作 Qt widget。
    # 修复前后台线程直接调 InfoBar(parent=self.widget) 会令主线程事件循环卡死；
    # 修复后应经线程安全的 QTimer.singleShot 回主线程再弹提示。
    _app()
    from ui.settings_tab import SettingsTab
    import qfluentwidgets

    tab = SettingsTab(_Ctx())

    main_tid = threading.main_thread().ident
    calls = []
    real_success = qfluentwidgets.InfoBar.success
    real_error = qfluentwidgets.InfoBar.error

    def _mk(tag):
        def wrap(*a, **k):
            calls.append((tag, threading.get_ident() == main_tid))
        return wrap

    qfluentwidgets.InfoBar.success = _mk("success")
    qfluentwidgets.InfoBar.error = _mk("error")
    try:
        tab._test_mcp()
        deadline = time.monotonic() + 2.0
        while not calls and time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.05)
    finally:
        qfluentwidgets.InfoBar.success = real_success
        qfluentwidgets.InfoBar.error = real_error

    assert calls, "点击测试连接后应通过 singleShot 调度回主线程弹提示"
    for tag, on_main in calls:
        assert on_main, f"InfoBar({tag}) 必须在主线程调用，后台线程直接操作 GUI 会卡死 UI"
