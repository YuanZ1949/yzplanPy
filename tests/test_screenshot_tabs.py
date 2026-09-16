"""截图模块 4 个 tab 构建器拆分（screenshot_tabs.py）与工厂迁移测试。

覆盖：
1) tab_widget.count() == 5 且标题顺序正确；
2) 设置 tab 内 QPushButton/QLineEdit/QComboBox 全部来自 ui/widgets.py 工厂
   （工厂产物带 QSS，裸建控件无 QSS —— 工厂产物与裸类同类型，故以 QSS 区分）；
3) 子进程冒烟：构造 widget → 逐 tab 点击主截图按钮 → 进度条出现 → 关闭，
   打印 SCREENSHOT_TABS_OK。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139）。
from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication
QTabWidget = QtWidgets.QTabWidget
QPushButton = QtWidgets.QPushButton
QLineEdit = QtWidgets.QLineEdit
QComboBox = QtWidgets.QComboBox
QMessageBox = QtWidgets.QMessageBox
QKeySequenceEdit = QtWidgets.QKeySequenceEdit

from core.config import AppConfig
from modules.screenshot.screenshot_ui import ScreenshotWidget

EXPECTED_TABS = ["窗口截图", "HTML 截图", "区域截图", "窗口列表", "设置"]


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _context(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    return type("Ctx", (), {"config": cfg, "host_window": None, "app": _app()})()


def _find_tab_widget(widget):
    return widget.findChild(QTabWidget)


# ── 单元：5 tab 结构 ────────────────────────────────────────────────────

_COMPOSITE_TYPES = (QKeySequenceEdit, QtWidgets.QAbstractSpinBox)


def _inside_composite(ctrl):
    """控件是否位于无工厂的复合控件（QKeySequenceEdit/QAbstractSpinBox）内部。"""
    parent = ctrl.parent()
    while parent is not None:
        if isinstance(parent, _COMPOSITE_TYPES):
            return True
        parent = parent.parent()
    return False


def test_settings_tab_no_raw_factory_controls(tmp_path):
    """设置 tab 内 QPushButton/QLineEdit/QComboBox 必须全部来自工厂（带 QSS）。"""
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    settings = tabs.widget(4)
    for cls in (QPushButton, QLineEdit, QComboBox):
        for ctrl in settings.findChildren(cls):
            if _inside_composite(ctrl):
                continue  # 复合控件内部子控件非工厂产物
            assert ctrl.styleSheet().strip(), (
                f"设置 tab 存在裸建 {cls.__name__}（无工厂 QSS）")
    w.close()


# ── 单元：按窗口类名截图 UI ─────────────────────────────────────────────

def test_window_tab_has_class_capture_controls(tmp_path):
    """窗口截图 tab 应包含窗口类名输入框与截图按钮（工厂产物）。"""
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    window_tab = tabs.widget(0)
    assert isinstance(w.window_class_input, QLineEdit)
    assert isinstance(w.capture_class_btn, QPushButton)
    assert w.capture_class_btn.text() == "截图"
    assert w.capture_class_btn.styleSheet().strip(), "类名截图按钮应来自工厂（带 QSS）"
    assert w.window_class_input.styleSheet().strip(), "类名输入框应来自工厂（带 QSS）"
    assert w.window_class_input in window_tab.findChildren(QLineEdit)
    assert w.capture_class_btn in window_tab.findChildren(QPushButton)
    w.close()


def test_capture_by_class_calls_core(tmp_path, monkeypatch):
    """触发类名截图按钮应调用 core.capture_window_by_class（monkeypatch 记录）。"""
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    w.window_class_input.setText("Chrome_WidgetWin_1")

    calls = []
    shot = tmp_path / "shot.png"
    monkeypatch.setattr(
        w.core, "capture_window_by_class",
        lambda cls, filename=None: calls.append(cls) or str(shot))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    w.capture_class_btn.click()
    if w.worker is not None:
        w.worker.wait(3000)
    assert calls == ["Chrome_WidgetWin_1"]
    w.close()


def test_capture_by_class_empty_input_warns(tmp_path, monkeypatch):
    """类名为空时点击截图应提示且不启动操作。"""
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    w.window_class_input.setText("   ")

    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a))
    started = []
    monkeypatch.setattr(w, "start_operation",
                        lambda op, **kw: started.append((op, kw)))

    w.capture_by_class()
    assert warned, "空类名应弹出警告"
    assert started == []
    w.close()


# ── 子进程冒烟：逐 tab 点击主截图按钮 → 进度条出现 → 关闭 ───────────────

class _FakeCore:
    """桩 core：capture 方法不真正截图，仅短暂阻塞后返回路径。"""

    def __init__(self):
        import tempfile
        self._dir = tempfile.mkdtemp()

    def _shot(self):
        import time
        time.sleep(0.3)
        return str(Path(self._dir) / "shot.png")

    def list_windows(self):
        return []

    def unregister_hotkey(self):
        return None

    def capture_full_screen(self, filename=None):
        return self._shot()

    def capture_window_by_title(self, title="", filename=None):
        return self._shot()

    def capture_yzplan_window(self, filename=None):
        return self._shot()

    def capture_window(self, hwnd=0, filename=None):
        return self._shot()

    def capture_region(self, x=0, y=0, width=800, height=600, filename=None):
        return self._shot()

    def capture_html_file_sync(self, html_path="", filename=None,
                               width=1920, height=1080):
        return self._shot()


def test_tabs_smoke_subprocess():
    """Subprocess isolation: build widget → click capture → progress bar → close."""
    import os
    import subprocess
    child_name = "test_tabs_smoke_child"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_screenshot_tabs.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )
    assert "SCREENSHOT_TABS_OK" in result.stdout.decode(errors="replace")


def test_tabs_smoke_child():
    """Child: build widget → iterate tabs → click capture buttons → close."""
    import tempfile

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # 屏蔽模态对话框，避免 worker 完成回调阻塞
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: None)

    cfg = AppConfig(path=str(Path(tempfile.mkdtemp()) / "settings.json"))
    ctx = type("Ctx", (), {"config": cfg, "host_window": None, "app": app})()

    w = ScreenshotWidget(context=ctx)
    w.core = _FakeCore()
    tabs = _find_tab_widget(w)
    assert tabs is not None
    assert tabs.count() == 5, f"应包含 5 个 tab，实际 {tabs.count()}"
    assert [tabs.tabText(i) for i in range(5)] == EXPECTED_TABS

    w.resize(900, 700)
    w.show()
    for _ in range(10):
        QApplication.processEvents()

    # 逐 tab 切换不崩
    for i in range(5):
        tabs.setCurrentIndex(i)
        for _ in range(5):
            QApplication.processEvents()

    # 窗口 tab：点击全屏截图按钮 → 进度条出现
    w.capture_screen_btn.click()
    assert w.progress_bar.isVisible(), "点击截图按钮后进度条应可见"
    if w.worker is not None:
        w.worker.wait(3000)

    # HTML tab：填入真实路径后点击截图按钮
    html_file = Path(tempfile.mkdtemp()) / "page.html"
    html_file.write_text("<html><body>ok</body></html>", encoding="utf-8")
    w.html_path_input.setText(str(html_file))
    assert w.capture_html_btn.isEnabled(), "填入路径后 HTML 截图按钮应启用"
    w.capture_html_btn.click()
    if w.worker is not None:
        w.worker.wait(3000)

    # 区域 tab：点击区域截图按钮
    w.capture_region_btn.click()
    if w.worker is not None:
        w.worker.wait(3000)

    # 窗口列表 tab：选中一项后点击截图按钮
    from PySide6.QtWidgets import QListWidgetItem
    item = QListWidgetItem("测试窗口 [class] (hwnd: 1)")
    item.setData(0x0100, 1)  # Qt.UserRole
    w.window_list.addItem(item)
    w.window_list.setCurrentItem(item)
    assert w.capture_selected_btn.isEnabled(), "选中窗口后截图按钮应启用"
    w.capture_selected_btn.click()
    if w.worker is not None:
        w.worker.wait(3000)

    w.close()
    for _ in range(5):
        QApplication.processEvents()
    print("SCREENSHOT_TABS_OK")