"""截图模块页可见性测试：模块页完整暴露 5 个 tab 且热键设置可操作。

审计结论：modules/screenshot/module.py 的 create_page 已返回完整 ScreenshotWidget
（窗口截图 / HTML 截图 / 区域截图 / 窗口列表 / 设置 共 5 个 tab），ui/module_pages.py
通过 mod.create_page(parent) 将其宿主到模块页窗口。本测试锁定该可见性保证，
防止未来回归导致用户再次看到"功能缺失"。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139），
# qt_bootstrap 模块级 _preload_icu() 在进程内预载 ICU DLL 后 Qt 才能加载。
# 本文件的子进程测试（test_module_page_smoke_no_crash_child）是全新进程，
# 直接 import 必然崩溃；其余测试文件因全量运行时 PySide6 已先行加载而幸免。
from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication
QTabWidget = QtWidgets.QTabWidget
QCheckBox = QtWidgets.QCheckBox
QKeySequenceEdit = QtWidgets.QKeySequenceEdit

from core.config import AppConfig
from modules.screenshot.module import Module
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


# ── 单元：模块页完整暴露 ScreenshotWidget（5 tab + 热键控件）──────────

def test_module_create_page_returns_full_screenshot_widget(tmp_path):
    ctx = _context(tmp_path)
    mod = Module(ctx)
    page = mod.create_page(None)
    assert isinstance(page, ScreenshotWidget), (
        "create_page 应返回 ScreenshotWidget，实际: %r" % type(page).__name__)

    tabs = _find_tab_widget(page)
    assert tabs is not None, "模块页应包含 QTabWidget"
    assert tabs.count() == 5, f"应包含 5 个 tab，实际 {tabs.count()}"
    assert [tabs.tabText(i) for i in range(5)] == EXPECTED_TABS

    # 设置 tab（最后一个）含热键启用开关 + 快捷键编辑框
    settings = tabs.widget(4)
    assert isinstance(settings.hotkey_enable_cb, QCheckBox)
    assert settings.hotkey_enable_cb.text() == "启用全局快捷键"
    assert isinstance(settings.hotkey_seq_edit, QKeySequenceEdit)
    page.close()


def test_module_page_hotkey_toggle_operable(tmp_path):
    """热键启用开关可操作：打开后快捷键编辑框可用，关闭后禁用。"""
    ctx = _context(tmp_path)
    mod = Module(ctx)
    page = mod.create_page(None)
    tabs = _find_tab_widget(page)
    settings = tabs.widget(4)

    # 默认配置 hotkey_enabled=False → 编辑框初始禁用
    assert settings.hotkey_enable_cb.isChecked() is False
    assert settings.hotkey_seq_edit.isEnabled() is False

    # 打开 → 编辑框可用
    settings.hotkey_enable_cb.setChecked(True)
    assert settings.hotkey_seq_edit.isEnabled() is True

    # 关闭 → 编辑框禁用
    settings.hotkey_enable_cb.setChecked(False)
    assert settings.hotkey_seq_edit.isEnabled() is False
    page.close()


# ── 子进程冒烟：打开模块页 → 5 tab → 热键开关两次 → 关闭 ─────────────

def test_module_page_smoke_no_crash_subprocess():
    """Subprocess isolation: open module page → 5 tabs → hotkey toggle → close."""
    import subprocess
    from pathlib import Path
    child_name = "test_module_page_smoke_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_screenshot_module_page.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
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


def test_module_page_smoke_no_crash_child():
    """Child: open module page → assert 5 tabs → toggle hotkey twice → close."""
    import tempfile
    from pathlib import Path

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    cfg = AppConfig(path=str(Path(tempfile.mkdtemp()) / "settings.json"))
    ctx = type("Ctx", (), {"config": cfg, "host_window": None, "app": app})()

    mod = Module(ctx)
    page = mod.create_page(None)
    page.resize(900, 700)
    page.show()
    for _ in range(10):
        QApplication.processEvents()

    tabs = _find_tab_widget(page)
    assert tabs is not None
    assert tabs.count() == 5, f"应包含 5 个 tab，实际 {tabs.count()}"
    assert [tabs.tabText(i) for i in range(5)] == EXPECTED_TABS

    # 设置 tab 热键控件存在且可操作
    settings = tabs.widget(4)
    assert isinstance(settings.hotkey_enable_cb, QCheckBox)
    assert isinstance(settings.hotkey_seq_edit, QKeySequenceEdit)

    # 热键启用开关切换两次：on → off
    settings.hotkey_enable_cb.setChecked(True)
    assert settings.hotkey_seq_edit.isEnabled() is True
    settings.hotkey_enable_cb.setChecked(False)
    assert settings.hotkey_seq_edit.isEnabled() is False

    # 关闭
    page.close()
    for _ in range(5):
        QApplication.processEvents()
    print("SCREENSHOT_TABS_OK")