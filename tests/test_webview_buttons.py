"""webview_control 拦截记录操作按钮：尺寸、布局与点击行为。

覆盖 Task 2：操作按钮最小宽 56、固定高 btn_height_md、200px 操作列内
三按钮几何不相交、点击触发对应动作；子进程冒烟 760px 窄窗渲染无异常、
拦截记录表行高 webview_row_height、内容换行开启、行高容纳 cell widget。
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
    # 应用全局 QSS，复现真实渲染盒模型（全量测试中主题 QSS 异步重刷后
    # 按钮会被 min-height+padding+border 抬高到 ~43px，超出 webview_row_height）
    from core.theme.qss_dark import _apply_dark_sheet
    _apply_dark_sheet(False)
    sz = sizing()
    container = _log_action_buttons("/x/A.exe", lambda *a: None)
    container.show()
    QApplication.processEvents()
    btns = _buttons(container)
    assert len(btns) == 3
    assert [b.text() for b in btns] == ["放行", "拦截", "删除"]
    margins = container.layout().contentsMargins()
    for b in btns:
        assert b.minimumWidth() == 56
        # make_button 拥有真实盒模型：渲染高度 == btn_height_md，且不超行高
        assert b.height() <= sz["webview_row_height"], (
            f"按钮渲染高 {b.height()}px 超过行高 {sz['webview_row_height']}px")
        assert b.sizeHint().height() + margins.top() + margins.bottom() <= sz["webview_row_height"], (
            f"按钮 sizeHint 高 {b.sizeHint().height()}px + 容器上下边距 "
            f"{margins.top() + margins.bottom()}px 超过行高 {sz['webview_row_height']}px")
    assert sz["webview_row_height"] >= sz["btn_height_md"], (
        f"行高 {sz['webview_row_height']}px 应 ≥ 按钮高 {sz['btn_height_md']}px")
    container.close()


def test_log_action_buttons_no_overlap_in_200px():
    _app()
    container = _log_action_buttons("/x/A.exe", lambda *a: None)
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
    container = _log_action_buttons("/x/A.exe", lambda e, a: calls.append((e, a)))
    btns = {b.text(): b for b in _buttons(container)}
    btns["放行"].click()
    btns["删除"].click()
    assert calls == [("/x/A.exe", "allow"), ("/x/A.exe", "forget")]


def _make_page(scan_data, host_log_data):
    """Build the merged webview page with controlled scan + log data (in-process)."""
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from modules.webview_control.module import Module

    _app()

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
    mod.host_log = list(host_log_data)

    import modules.webview_control.page as page_mod
    _orig_scan = page_mod.scan_hosts
    page_mod.scan_hosts = lambda blocked: list(scan_data)
    page = mod.create_page(None)
    page_mod.scan_hosts = _orig_scan

    page.resize(900, 600)
    page.show()
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)
    return mod, page


def test_webview_table_row_height_fits_cell_widget():
    """行高自适应：wordWrap 开启、行高 ≥ cell widget sizeHint、cell 不溢出。"""
    mod, page = _make_page(
        scan_data=[],
        host_log_data=[{
            "exe": r"C:\Apps\A.exe", "name": "A",
            "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
            "status": "pending",
        }],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert table.wordWrap() is True, "合并表未开启内容换行"
    assert table.rowCount() == 1
    for i in range(table.rowCount()):
        for c in (3, 7):
            cell = table.cellWidget(i, c)
            assert cell is not None, f"row {i} col {c} 无 cell widget"
            assert table.rowHeight(i) >= cell.sizeHint().height(), (
                f"row {i} col {c}: rowHeight {table.rowHeight(i)} < "
                f"cell sizeHint {cell.sizeHint().height()}")
            item = table.item(i, 0)
            assert cell.geometry().bottom() <= table.visualItemRect(item).bottom(), (
                f"row {i} col {c}: cell bottom {cell.geometry().bottom()} > "
                f"row bottom {table.visualItemRect(item).bottom()}")
    page.close()
    page.deleteLater()


def test_webview_action_buttons_vertical_insets_symmetric():
    """操作按钮在行内垂直居中：上/下 inset 差 ≤1px，按钮渲染高 ≤ 行高。

    复现真实盒模型：应用全局 QSS（QTableWidget::item padding 上下各 2px）后，
    cell widget 高度 = 行高 - 5px；若按钮容器上下边距过大，按钮会溢出 cell
    底部（下 inset 为负），即「按钮下边框过低」症状。
    """
    from core.theme.qss_dark import _apply_dark_sheet
    _app()
    _apply_dark_sheet(False)
    _, page = _make_page(
        scan_data=[],
        host_log_data=[{
            "exe": r"C:\Apps\A.exe", "name": "A",
            "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
            "status": "pending",
        }],
    )
    table = page.findChildren(QtWidgets.QTableWidget)[0]
    assert table.rowCount() >= 1
    for i in range(table.rowCount()):
        cell = table.cellWidget(i, 7)
        assert cell is not None, f"row {i} col 7 无按钮容器"
        btns = cell.findChildren(QtWidgets.QPushButton)
        assert btns, f"row {i} col 7 无按钮"
        row_h = table.rowHeight(i)
        c_top = cell.geometry().top()
        c_bottom = cell.geometry().bottom()
        for b in btns:
            assert b.height() <= row_h, (
                f"row {i} 按钮渲染高 {b.height()}px > 行高 {row_h}px")
            b_top = c_top + b.geometry().top()
            b_bottom = c_top + b.geometry().bottom()
            top_inset = b_top - c_top
            bottom_inset = c_bottom - b_bottom
            assert abs(top_inset - bottom_inset) <= 1, (
                f"row {i} 按钮 '{b.text()}' 上 inset {top_inset}px != 下 inset "
                f"{bottom_inset}px（差 {top_inset - bottom_inset}px）")
    page.close()
    page.deleteLater()


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
    """Child: 760px 窄窗渲染拦截记录页，行高 webview_row_height、按钮不重叠。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from core.theme.tokens import sizing
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
    assert log_table.verticalHeader().defaultSectionSize() == sizing()["webview_row_height"]
    assert log_table.wordWrap() is True, "合并表未开启内容换行"
    for i in range(log_table.rowCount()):
        for c in (3, 7):
            cell = log_table.cellWidget(i, c)
            if cell is None:
                continue
            assert log_table.rowHeight(i) >= cell.sizeHint().height(), (
                f"row {i} col {c}: rowHeight {log_table.rowHeight(i)} < "
                f"cell sizeHint {cell.sizeHint().height()}")

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