"""perf_monitor 表格进度条委托：_bar_text_color/_BarDelegate。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import _theme_colors
def _bar_text_color(r, g, b):
    """按条形色亮度挑选文字颜色：亮条->深字，暗条->白字。"""
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#0f0f0f" if lum >= 140 else "#ffffff"


class _BarDelegate(QtWidgets.QStyledItemDelegate):
    """在「操作」列绘制背景条形图 + 文字，条形长度反映该行的相对数值。"""

    def __init__(self, table, bar_col=0, value_col=2):
        super().__init__(table)
        self._table = table
        self._bar_col = bar_col
        self._value_col = value_col
        self._max_value = 1.0

    def set_max(self, v):
        self._max_value = max(v, 0.001)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        is_sel = bool(option.state & QtWidgets.QStyle.State_Selected)
        is_hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        tc = _theme_colors()

        # ── 背景 ──
        if is_sel:
            bg = QtGui.QColor(tc["sel_bg"])
        elif is_hover:
            bg = QtGui.QColor(128, 128, 128, 18)
        elif index.row() % 2 == 0:
            bg = QtGui.QColor(0, 0, 0, 0)
        else:
            bg = QtGui.QColor(128, 128, 128, 8)
        painter.fillRect(rect, bg)

        # ── 条形（仅 bar_col）──
        if index.column() == self._bar_col:
            val_item = self._table.item(index.row(), self._value_col)
            val = val_item.data(QtCore.Qt.UserRole) if val_item else 0
            val = float(val) if val is not None else 0.0
            ratio = val / self._max_value if self._max_value > 0 else 0
            ratio = min(1.0, max(0.0, ratio))

            bar_rect = QtCore.QRectF(rect.x() + 2, rect.y() + 3,
                                     (rect.width() - 8) * ratio, rect.height() - 6)
            colors = tc["bar_colors"]
            ci = min(int(ratio * (len(colors) - 1)), len(colors) - 1)
            r, g, b = colors[ci]
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(r, g, b, 140))
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.drawRoundedRect(bar_rect, 3, 3)

        # ── 文字 ──
        text = index.data(QtCore.Qt.DisplayRole)
        if text is not None:
            text = str(text).strip()
        if text:
            if option.widget:
                painter.setFont(option.widget.font())
            if index.column() == self._bar_col and ratio > 0.5:
                # 条形覆盖文字区：按条形自身亮度取黑/白字，保证对比度
                r, g, b = colors[ci]
                pen = QtGui.QColor(_bar_text_color(r, g, b))
            elif is_sel:
                pen = QtGui.QColor(255, 255, 255)
            else:
                pen = QtGui.QColor(tc["text_primary"])
            painter.setPen(pen)
            text_rect = rect.adjusted(6, 0, -4, 0)
            painter.drawText(text_rect,
                             int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                             text)
        painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QtCore.QSize(max(base.width(), 200), max(base.height(), 26))
