"""截图模块：全屏拖拽选区覆盖层（区域截图用）。

拖拽绘制选区矩形，释放时发射 region_selected(QRect)；Esc / 右键取消。
仅覆盖主屏（最小实现，无多显示器 / DPI 逻辑）。
"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.theme.tokens import rgba_to_qcolor, sizing, theme_palette


class RegionOverlay(QtWidgets.QWidget):
    """无边框全屏半透明覆盖层：拖拽选择屏幕区域。

    左键按下记录起点，拖动实时绘制选区，释放时发射归一化后的 QRect；
    Esc 或右键取消（发射 cancelled 并关闭）。
    """

    region_selected = QtCore.Signal(QtCore.QRect)
    cancelled = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._origin = None
        self._current = None
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.setFocus()

    def _selection_rect(self):
        """从起点/当前点计算选区矩形（终点为开区间，宽高 = 坐标差）。"""
        if self._origin is None or self._current is None:
            return QtCore.QRect()
        x1 = min(self._origin.x(), self._current.x())
        y1 = min(self._origin.y(), self._current.y())
        x2 = max(self._origin.x(), self._current.x())
        y2 = max(self._origin.y(), self._current.y())
        return QtCore.QRect(x1, y1, x2 - x1, y2 - y1)

    def paintEvent(self, event):
        p = theme_palette()
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), rgba_to_qcolor(p["overlay_dim"]))
        if self._origin is not None and self._current is not None:
            rect = self._selection_rect()
            painter.fillRect(rect, rgba_to_qcolor(p["overlay_sel_fill"]))
            painter.setPen(QtGui.QPen(
                rgba_to_qcolor(p["accent"]), sizing()["overlay_border_width"]))
            painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
            event.accept()
            return
        if event.button() == QtCore.Qt.RightButton:
            self._cancel()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._origin is not None:
            self._current = event.position().toPoint()
            rect = self._selection_rect()
            self._origin = None
            self._current = None
            self.update()
            if rect.width() > 0 and rect.height() > 0:
                self.region_selected.emit(rect)
            self.close()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _cancel(self):
        self._origin = None
        self._current = None
        self.update()
        self.cancelled.emit()
        self.close()