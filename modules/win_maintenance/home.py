"""win_maintenance 主页卡片：系统/应用日志错误与警告摘要统计。

点击卡片跳转模块页；30s 定时自动刷新；日志不可用时显示「暂无数据」。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel

_, QtCore, QtGui, QtWidgets = import_qt()

from .store import get_log_stats

_REFRESH_MS = 30000

_LEVEL_COLORS = {
    "错误": "status_error",
    "警告": "status_warning",
    "信息": "status_info",
}


class _HomeWidget(QtWidgets.QWidget):
    """主页摘要卡片：两行（系统/应用日志）级别计数，点击打开模块页。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setMinimumSize(220, 120)
        self.setCursor(QtGui.Qt.PointingHandCursor)
        p = theme_palette()

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        self._rows = {}
        for log_name in ("System", "Application"):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            name_lb = BodyLabel("系统日志" if log_name == "System" else "应用日志", self)
            name_lb.setStyleSheet(f"color: {p['text_secondary']};")
            row.addWidget(name_lb)
            row.addStretch(1)
            cells = {}
            for level in ("错误", "警告", "信息"):
                cell = BodyLabel("--", self)
                cell.setStyleSheet(f"color: {p[_LEVEL_COLORS[level]]};")
                row.addWidget(cell)
                cells[level] = cell
            lay.addLayout(row)
            self._rows[log_name] = cells

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self.destroyed.connect(self._stop_timer)
        self._refresh()

    def _stop_timer(self):
        try:
            self._timer.stop()
        except RuntimeError:
            pass

    def _refresh(self):
        for log_name, cells in self._rows.items():
            stats = get_log_stats(log_name)
            for level, cell in cells.items():
                cell.setText(str(stats.get(level, 0)))

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            from ui.module_pages import open_module_page
            try:
                open_module_page(self._owner, self)
            except Exception:
                pass
        super().mouseReleaseEvent(event)


def _make_home_widget(owner, parent):
    return _HomeWidget(owner, parent)