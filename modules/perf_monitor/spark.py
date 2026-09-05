"""perf_monitor 迷你折线：_draw_spark。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import _smooth_path
def _draw_spark(p, rect, data, color, y_max):
    """绘制迷你走势线（含底部渐变）。"""
    if not data or rect.width() < 8 or rect.height() < 4:
        return
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    points = []
    n = len(data)
    for i, v in enumerate(data):
        x = rect.left() + rect.width() * i / max(1, n - 1)
        y = rect.bottom() - (v / y_max) * rect.height()
        points.append(QtCore.QPointF(x, y))
    path = _smooth_path(points)
    if len(points) > 1:
        fill = QtGui.QPainterPath(path)
        fill.lineTo(points[-1].x(), rect.bottom())
        fill.lineTo(points[0].x(), rect.bottom())
        fill.closeSubpath()
        grad = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        c1 = QtGui.QColor(color)
        c1.setAlpha(70)
        c2 = QtGui.QColor(color)
        c2.setAlpha(0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(fill)
    line = QtGui.QColor(color)
    line.setAlpha(230)
    p.setPen(QtGui.QPen(line, 1.6))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(path)
    if points:
        last = points[-1]
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(color))
        p.drawEllipse(last, 2.4, 2.4)
