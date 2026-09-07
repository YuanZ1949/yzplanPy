"""Todo 9: 主题补齐标准控件边框 + 按钮文字/图标不重叠。"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _sheet(dark):
    if dark:
        from core.theme.qss_dark import _apply_dark_sheet

        _apply_dark_sheet(False)
    else:
        from core.theme.qss_light import _apply_light_sheet

        _apply_light_sheet(False)
    return QtWidgets.QApplication.instance().styleSheet()


def test_dark_sheet_has_standard_control_borders(_qapp):
    s = _sheet(True)
    assert "QPlainTextEdit, QTextEdit" in s, "深色主题应补齐多行输入框边框"
    assert "QCheckBox::indicator" in s, "深色主题应补齐复选框指示器边框"
    assert "QTableWidget" in s, "深色主题应补齐表格边框"
    assert "QHeaderView::section" in s, "深色主题应补齐表头（含复选框列）边框"
    assert "padding: 0 8px" in s, "深色主题 QToolButton 应有全局内边距"


def test_light_sheet_has_standard_control_borders(_qapp):
    s = _sheet(False)
    assert "QPlainTextEdit, QTextEdit" in s, "浅色主题应补齐多行输入框边框"
    assert "QCheckBox::indicator" in s, "浅色主题应补齐复选框指示器边框"
    assert "QTableWidget" in s, "浅色主题应补齐表格边框"
    assert "QHeaderView::section" in s, "浅色主题应补齐表头（含复选框列）边框"
    assert "padding: 0 8px" in s, "浅色主题 QToolButton 应有全局内边距"


def test_title_bar_tool_buttons_widen_for_icon_and_text(_qapp):
    """定制标题栏 icon+文字按钮宽度 >= 88，文字与图标不重叠。"""
    from qfluentwidgets import FluentIcon, ToolButton

    btn = ToolButton(FluentIcon.SETTING)
    btn.setText("设置")
    btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    text_w = btn.fontMetrics().horizontalAdvance("设置")
    btn.setFixedSize(max(88, text_w + 48), 30)
    assert btn.width() >= 88, "icon+文字按钮最小宽度应 >= 88"
    assert btn.width() >= text_w + 48, "按钮宽度应容纳图标+文字+内边距"