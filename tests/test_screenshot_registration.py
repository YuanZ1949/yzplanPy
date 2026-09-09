"""截图模块注册测试：验证 ModuleRegistry 能发现并启用 screenshot 模块。"""
import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.config import AppConfig
from modules.registry import ModuleContext, ModuleRegistry


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _registry():
    _app()
    config = AppConfig()
    context = ModuleContext(config=config, host_window=None, app=_app())
    return ModuleRegistry(context)


def test_screenshot_module_registered():
    reg = _registry()
    ids = [m.id for m in reg.all()]
    assert "screenshot" in ids, f"screenshot 应被注册，实际模块列表: {ids}"


def test_screenshot_module_enabled_by_default():
    reg = _registry()
    assert reg.is_enabled("screenshot") is True


def test_screenshot_module_get():
    reg = _registry()
    mod = reg.get("screenshot")
    assert mod is not None
    assert mod.MODULE_ID == "screenshot"
