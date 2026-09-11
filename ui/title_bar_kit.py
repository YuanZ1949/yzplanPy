"""标题栏紧凑控件库：主窗口与模块窗口共用的带文字标题栏按钮与竖向分隔线。

从 ui/mainwindow.py 原样抽取（行为不变），供主窗口 _CustomTitleBar 与模块窗口
（RSS 等）自定义标题栏复用，保证两处观感完全统一。
"""

from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentTitleBarButton

_, QtCore, QtGui, QtWidgets = import_qt()


class _TextTitleBarButton(FluentTitleBarButton):
    """带文字的标题栏按钮：图标+文字。

    复用 TitleBarButton 状态机（NORMAL/HOVER/PRESSED）与 _getColors()，
    文字与图标使用同一主题色（由 FLUENT_WINDOW QSS 注入），
    因此与纯图标标题栏按钮的外观风格完全统一。
    """

    _FONT = QtGui.QFont("Microsoft YaHei", 9)

    def __init__(self, icon, text, parent=None):
        super().__init__(icon, parent)
        self._text = text
        metric = QtGui.QFontMetrics(self._FONT)
        tw = metric.horizontalAdvance(text)
        # 紧凑规格：固定高 28、最小宽 0、水平 Maximum（可收缩不可扩张）、内边距 2px 8px
        self.setFixedHeight(28)
        self.setMinimumWidth(0)
        self.setMaximumWidth(14 + 6 + tw + 16)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        metric = QtGui.QFontMetrics(self._FONT)
        tw = metric.horizontalAdvance(self._text)
        # 图标 14 + 间距 6 + 文字 + 两侧内边距 16（8px/侧）
        return QtCore.QSize(14 + 6 + tw + 16, 28)

    def paintEvent(self, event):
        from qfluentwidgets.common.icon import drawIcon

        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
        )
        color, bg_color = self._getColors()

        # 背景（与原生标题栏按钮一致）
        painter.setBrush(bg_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(self.rect())

        # 图标（左侧）
        drawIcon(self._icon, painter, QtCore.QRectF(8, (self.height() - 14) / 2, 14, 14))

        # 文字（与图标同色，主题自适应）
        painter.setPen(color)
        painter.setFont(self._FONT)
        painter.drawText(
            QtCore.QRectF(8 + 14 + 6, 0, self.width() - (8 + 14 + 6) - 8, self.height()),
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
            self._text,
        )


class _VLine(QtWidgets.QWidget):
    """标题栏竖向分隔线（主题自适应细线），用于功能分组隔离。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 与按钮同高，保证进出 buttonLayout 后垂直对齐一致；线画在垂直居中。
        self.setFixedSize(10, 28)

    def paintEvent(self, event):
        from core.theme import resolve_dark

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if resolve_dark("auto"):
            color = QtGui.QColor(255, 255, 255, 50)
        else:
            color = QtGui.QColor(0, 0, 0, 30)
        painter.setPen(color)
        painter.drawLine(5, 6, 5, self.height() - 6)
        painter.end()