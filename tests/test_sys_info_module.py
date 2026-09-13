"""sys_info 模块独立页面测试：Module.create_page 渲染配置信息页。

Task 10: modules/sys_info.py 的 Module 此前没有 create_page 覆写，
基类默认返回 None → 模块选项卡/模块页窗口显示"该模块没有独立页面"。
本测试锁定 create_page 返回真实配置信息页（4 张分组卡片 + 刷新/复制按钮），
并做子进程冒烟（打开→渲染→关闭），防止回归。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139），
# qt_bootstrap 模块级 _preload_icu() 在进程内预载 ICU DLL 后 Qt 才能加载。
# 本文件的子进程测试（test_module_page_smoke_no_crash_child）是全新进程，
# 直接 import 必然崩溃；其余测试因全量运行时 PySide6 已先行加载而幸免。
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.config import AppConfig
from modules.sys_info import Module


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _context(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    return type("Ctx", (), {"config": cfg, "host_window": None, "app": _app()})()


def test_module_create_page_returns_info_widget(tmp_path):
    """create_page 返回 QWidget 且渲染 4 张配置卡片（硬件/系统/网络/软件）。"""
    from qfluentwidgets import GroupHeaderCardWidget
    ctx = _context(tmp_path)
    mod = Module(ctx)
    page = mod.create_page(None)
    assert page is not None
    assert isinstance(page, QtWidgets.QWidget), (
        "create_page 应返回 QWidget，实际: %r" % type(page).__name__)
    cards = page.findChildren(GroupHeaderCardWidget)
    assert len(cards) == 4
    titles = [c.getTitle() for c in cards]
    for name in ("硬件", "系统", "网络", "软件"):
        assert name in titles
    page.close()


def test_module_page_smoke_no_crash_subprocess():
    """Subprocess isolation: 打开→渲染→关闭配置信息页 (0xC0000005 guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_module_page_smoke_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_sys_info_module.py::{child_name}",
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
    assert "SYSINFO_PAGE_OK" in result.stdout.decode(errors="replace")


def test_module_page_smoke_no_crash_child():
    """Child: Module(ctx).create_page(None) → show → 断言卡片与按钮 → close。"""
    import tempfile
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    cfg = AppConfig(path=str(Path(tempfile.mkdtemp()) / "settings.json"))
    ctx = type("Ctx", (), {"config": cfg, "host_window": None, "app": app})()

    mod = Module(ctx)
    page = mod.create_page(None)
    page.resize(900, 700)
    page.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()

    from qfluentwidgets import GroupHeaderCardWidget
    cards = page.findChildren(GroupHeaderCardWidget)
    assert len(cards) == 4, f"应包含 4 张卡片，实际 {len(cards)}"
    assert page.findChildren(QtWidgets.QPushButton), "页面应包含按钮"

    page.close()
    page.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("SYSINFO_PAGE_OK")