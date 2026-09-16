"""截图模块注册测试：验证 ModuleRegistry 能发现并启用 screenshot 模块。"""
import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.config import AppConfig
from modules.registry import ModuleContext, ModuleRegistry
from modules.screenshot.screenshot_ui import ScreenshotWidget


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


def _context(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    return type("Ctx", (), {"config": cfg, "host_window": None, "app": _app()})()


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


# ── 关闭窗口生命周期：注销热键 + 安全停止 worker ────────────────────────

def test_close_event_unregisters_hotkey(tmp_path, monkeypatch):
    """关闭窗口必须注销全局热键。

    缺陷 1.1：ScreenshotWidget 无 closeEvent → unregister_hotkey() 永不调用，
    installNativeEventFilter 登记对象随 GC 销毁 → 悬垂指针，下一次原生事件崩溃。
    """
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    calls = []
    monkeypatch.setattr(w.core, "unregister_hotkey", lambda: calls.append("unregister"))
    w.close()
    assert calls == ["unregister"], (
        "closeEvent 应调用 core.unregister_hotkey()，实际调用: %r" % calls)


def test_close_event_interrupts_running_worker(tmp_path):
    """截图进行中关闭窗口必须中断并等待 worker。

    缺陷 4.2：self.worker 无父对象、无 closeEvent → 截图进行中关窗触发
    "QThread: Destroyed while thread is still running" 崩溃。
    """
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)

    class FakeWorker:
        def __init__(self):
            self.interrupted = False
            self.waited = False
            self.wait_ms = None

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def wait(self, ms):
            self.waited = True
            self.wait_ms = ms
            return True

    fake = FakeWorker()
    setattr(w, "worker", fake)
    w.close()
    assert fake.interrupted is True, "closeEvent 应调用 worker.requestInterruption()"
    assert fake.waited is True, "closeEvent 应调用 worker.wait()"
    assert fake.wait_ms == 2000, f"wait 超时应为 2000ms，实际 {fake.wait_ms}"



