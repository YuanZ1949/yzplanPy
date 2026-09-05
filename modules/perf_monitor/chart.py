"""perf_monitor 实时曲线图：_LineChart。"""
import collections
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import _nice_ceil, _smooth_path, _theme_colors
class _LineChart(QtWidgets.QWidget):
    """自定义实时折线图：网格 + 平滑曲线 + 渐变填充 + 实时当前值。"""

    POINTS = 120

    def __init__(self, title, color, unit, y_max=None, parent=None):
        super().__init__(parent)
        self._title = title
        self._color = QtGui.QColor(color)
        self._unit = unit
        self._y_max = y_max
        self._data = collections.deque(maxlen=self.POINTS)
        self._max_seen = 0.0
        self.setMinimumHeight(140)
        self.setMinimumWidth(140)

    def push(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self._data.append(v)
        if v > self._max_seen:
            self._max_seen = v
        self.update()

    def clear_all(self):
        self._data.clear()
        self._max_seen = 0.0
        self.update()

    def _y_scale(self):
        if self._y_max:
            return float(self._y_max)
        if self._max_seen <= 0:
            return 64.0
        return _nice_ceil(self._max_seen * 1.15)

    def _font(self, size=7.5, bold=False):
        f = QtGui.QFont(self.font())
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def paintEvent(self, _event):
        tc = _theme_colors()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w <= 40 or h <= 40:
            p.end()
            return

        left, top, right, bottom = 36, 18, 10, 16
        plot = QtCore.QRectF(left, top, w - left - right, h - top - bottom)
        sec = QtGui.QColor(tc["text_secondary"])
        pri = QtGui.QColor(tc["text_primary"])

        # ── 网格与刻度 ──
        ymax = self._y_scale()
        n_steps = 4
        for i in range(n_steps + 1):
            yy = plot.top() + plot.height() * i / n_steps
            grid = QtGui.QColor(sec)
            grid.setAlpha(46)
            p.setPen(QtGui.QPen(grid, 1))
            p.drawLine(QtCore.QPointF(plot.left(), yy), QtCore.QPointF(plot.right(), yy))
            lab = QtGui.QColor(sec)
            lab.setAlpha(170)
            p.setFont(self._font(7.5))
            p.setPen(lab)
            val = ymax * (n_steps - i) / n_steps
            text = f"{val:.0f}" if val >= 10 else f"{val:.1f}"
            p.drawText(QtCore.QRectF(0, yy - 8, left - 5, 16),
                       int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight), text)

        # ── 标题与当前值 ──
        p.setFont(self._font(7.5))
        p.setPen(sec)
        p.drawText(QtCore.QRectF(plot.left(), 0, plot.width() * 0.7, 16),
                   int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), self._title)

        pts = list(self._data)
        if not pts:
            p.setPen(sec)
            p.drawText(plot, QtCore.Qt.AlignCenter, "等待数据…")
            p.end()
            return

        cur = pts[-1]
        p.setFont(self._font(8, bold=True))
        p.setPen(self._color)
        p.drawText(QtCore.QRectF(plot.left() + plot.width() * 0.3, 0, plot.width() * 0.7, 16),
                   int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight),
                   f"{cur:.1f} {self._unit}".strip())

        # ── 曲线 ──
        points = []
        for i, v in enumerate(pts):
            x = plot.left() + plot.width() * i / (self.POINTS - 1)
            y = plot.bottom() - (v / ymax) * plot.height()
            points.append(QtCore.QPointF(x, y))

        path = _smooth_path(points)
        if len(points) > 1:
            fill = QtGui.QPainterPath(path)
            fill.lineTo(points[-1].x(), plot.bottom())
            fill.lineTo(points[0].x(), plot.bottom())
            fill.closeSubpath()
            grad = QtGui.QLinearGradient(0, plot.top(), 0, plot.bottom())
            c1 = QtGui.QColor(self._color)
            c1.setAlpha(85)
            c2 = QtGui.QColor(self._color)
            c2.setAlpha(0)
            grad.setColorAt(0, c1)
            grad.setColorAt(1, c2)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(grad)
            p.drawPath(fill)

        line = QtGui.QColor(self._color)
        line.setAlpha(235)
        p.setPen(QtGui.QPen(line, 2))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(path)

        # ── 最新点 ──
        last = points[-1]
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(pri))
        p.drawEllipse(last, 3.2, 3.2)
        p.setBrush(self._color)
        p.drawEllipse(last, 2.0, 2.0)
        p.end()
