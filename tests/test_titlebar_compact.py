"""标题栏按钮紧凑化回归测试（Task 7）。

验证主窗口 _TextTitleBarButton / _VLine 的紧凑规格：
固定高 28、最小宽 0、水平 Maximum / 垂直 Fixed、内边距 2px 8px（宽度紧凑）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication, QSizePolicy

app = QApplication.instance() or QApplication([])

from qfluentwidgets import FluentIcon
from ui.mainwindow import _TextTitleBarButton, _VLine


def test_titlebar_text_button_compact_spec():
    btn = _TextTitleBarButton(FluentIcon.SETTING, "设置")
    assert btn.height() == 28, "按钮固定高度应为 28"
    assert btn.minimumWidth() == 0, "按钮最小宽度应为 0"
    sp = btn.sizePolicy()
    assert sp.horizontalPolicy() == QSizePolicy.Maximum, "水平策略应为 Maximum（可收缩不可扩张）"
    assert sp.verticalPolicy() == QSizePolicy.Fixed, "垂直策略应为 Fixed"
    # 紧凑宽度：内边距 8px/侧，不占标题栏 50% 以上
    hint = btn.sizeHint()
    assert hint.height() == 28, "sizeHint 高度应为 28"
    assert hint.width() < 120, f"按钮宽度应紧凑, 实际: {hint.width()}"


def test_titlebar_text_button_compact_widths():
    # 不同文字长度下宽度均紧凑且随文字增长
    short = _TextTitleBarButton(FluentIcon.ADD, "布局")
    long = _TextTitleBarButton(FluentIcon.ADD, "添加组件")
    assert short.sizeHint().width() < long.sizeHint().width(), "宽度应随文字增长"
    assert long.sizeHint().width() < 120, f"最长按钮宽度应紧凑, 实际: {long.sizeHint().width()}"


def test_titlebar_vline_height_matches_buttons():
    line = _VLine()
    assert line.height() == 28, "分隔线高度应与按钮一致 (28)"