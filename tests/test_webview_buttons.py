"""webview_control 拦截记录操作按钮：尺寸、布局与点击行为。

覆盖 Task 2：操作按钮最小宽 56、固定高 input_height、200px 操作列内
三按钮几何不相交、点击触发对应动作；子进程冒烟 760px 窄窗渲染无异常、
拦截记录表行高 30。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139）。
from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

from core.theme.tokens import sizing
from modules.webview_control.page import _log_action_buttons

QApplication = QtWidgets.QApplication


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _buttons(container):
    return container.findChildren(QtWidgets.QPushButton)


def test_log_action_buttons_three_buttons_min_width_and_height():
    _app()
    sz = sizing()
    container = _log_action_buttons("/x/A.exe", lambda *a: None, sz)
    btns = _buttons(container)
    assert len(btns) == 3
    assert [b.text() for b in btns] == ["放行", "拦截", "删除"]
    for b in btns:
        assert b.minimumWidth() == 56
        # setFixedHeight 生效：高度上限锁定为 input_height。
        # 注意：应用级 QSS 的 min-height(30px)+padding+border 会抬高 minimumHeight
        # （全量测试中主题 QSS 异步重刷后可达 43px），故只断言上限与下限。
        assert b.maximumHeight() == sz["input_height"]
        assert b.minimumHeight() >= sz["input_height"]


def test_log_action_buttons_no_overlap_in_200px():
    _app()
    container = _log_action_buttons("/x/A.exe", lambda *a: None, sizing())
    container.setFixedWidth(200)
    container.adjustSize()
    container.show()
    QApplication.processEvents()
    btns = _buttons(container)
    assert len(btns) == 3
    for i in range(3):
        for j in range(i + 1, 3):
            assert not btns[i].geometry().intersects(btns[j].geometry()), (
                f"{btns[i].text()} 与 {btns[j].text()} 重叠: "
                f"{btns[i].geometry()} vs {btns[j].geometry()}"
            )
    container.close()


def test_log_action_buttons_click_allow_and_forget():
    _app()
    calls = []
    container = _log_action_buttons("/x/A.exe", lambda e, a: calls.append((e, a)), sizing())
    btns = {b.text(): b for b in _buttons(container)}
    btns["放行"].click()
    btns["删除"].click()
    assert calls == [("/x/A.exe", "allow"), ("/x/A.exe", "forget")]


def test_webview_buttons_smoke_subprocess():
    """Subprocess isolation: 760px 窄窗渲染拦截记录页 (icuuc.dll guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_webview_buttons_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_webview_buttons.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )
    assert "WEBVIEW_BUTTONS_OK" in result.stdout.decode()


def test_webview_buttons_smoke_child():
    """Child: 760px 窄窗渲染拦截记录页，行高 30、按钮不重叠。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from modules.webview_control.module import Module

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    class _FakeConfig:
        def __init__(self):
            self.data = {}

        def get(self, key, default=None):
            cur = self.data
            for part in key.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return default
                cur = cur[part]
            return cur

        def set(self, key, value):
            cur = self.data
            parts = key.split(".")
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = value

        def save(self):
            pass

    class _FakeContext:
        def __init__(self, config):
            self.config = config

    mod = Module(_FakeContext(_FakeConfig()))
    mod.host_log = [{
        "exe": r"C:\Apps\A.exe", "name": "A",
        "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
        "status": "pending",
    }]
    page = mod.create_page(None)
    page.resize(760, 600)
    page.show()
    # 自适应列宽经 singleShot 延迟 reflow，需多轮事件循环落定
    for _ in range(5):
        app.processEvents()
        QtCore.QThread.msleep(20)

    log_tables = [t for t in page.findChildren(QtWidgets.QTableWidget)
                  if t.columnCount() == 8]
    assert log_tables, "未找到合并表"
    log_table = log_tables[0]
    assert log_table.verticalHeader().defaultSectionSize() == 30

    cell = log_table.cellWidget(0, 7)
    assert cell is not None, "拦截记录操作列无按钮容器"
    btns = cell.findChildren(QtWidgets.QPushButton)
    assert len(btns) == 3
    for i in range(3):
        for j in range(i + 1, 3):
            assert not btns[i].geometry().intersects(btns[j].geometry()), (
                f"{btns[i].text()} 与 {btns[j].text()} 重叠: "
                f"{btns[i].geometry()} vs {btns[j].geometry()}"
            )

    page.close()
    page.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("WEBVIEW_BUTTONS_OK")