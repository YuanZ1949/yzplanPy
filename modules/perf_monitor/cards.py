"""perf_monitor 指标卡片：_paint_metric_icon/_IconBadge/_MetricCard/_make_metric_card。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from qfluentwidgets import BodyLabel, StrongBodyLabel
from .styles import _theme_colors
def _paint_metric_icon(painter, cx, cy, s, kind, color):
    """在画布上绘制一小枚几何图标（无需字体，随主题渲染）。"""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color), max(1.6, s / 11.0))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    col = QtGui.QColor(color)
    h = s * 0.42

    if kind == "pid":
        w = s * 0.20
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(col)
        for dx in (-s * 0.25, s * 0.25):
            painter.drawRoundedRect(QtCore.QRectF(cx + dx - w / 2, cy - h, w, h * 2), 1, 1)
        for dy in (-s * 0.25, s * 0.25):
            painter.drawRoundedRect(QtCore.QRectF(cx - h, cy + dy - w / 2, h * 2, w), 1, 1)
    elif kind == "cpu":
        painter.drawRoundedRect(
            QtCore.QRectF(cx - s * 0.30, cy - s * 0.30, s * 0.60, s * 0.60),
            s * 0.07, s * 0.07)
        painter.setBrush(col)
        painter.setPen(QtCore.Qt.NoPen)
        pin = s * 0.05
        for px, py in ((cx - s * 0.30, cy - s * 0.30), (cx + s * 0.30, cy - s * 0.30),
                        (cx - s * 0.30, cy + s * 0.30), (cx + s * 0.30, cy + s * 0.30)):
            painter.drawRect(QtCore.QRectF(px - pin, py - pin, pin * 2, pin * 2))
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(QtCore.QPointF(cx, cy), s * 0.11, s * 0.11)
    elif kind == "memory":
        painter.drawRoundedRect(
            QtCore.QRectF(cx - s * 0.20, cy - h, s * 0.40, h * 2), s * 0.05, s * 0.05)
        for dy in (-s * 0.21, 0.0, s * 0.21):
            painter.drawLine(QtCore.QPointF(cx - s * 0.14, cy + dy),
                             QtCore.QPointF(cx + s * 0.14, cy + dy))
    elif kind == "threads":
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(col)
        bar_h = s * 0.10
        for i, dy in enumerate((-s * 0.28, 0.0, s * 0.28)):
            bar_w = s * 0.46 if i != 1 else s * 0.62
            painter.drawRoundedRect(
                QtCore.QRectF(cx - bar_w / 2, cy + dy - bar_h / 2, bar_w, bar_h),
                bar_h / 2, bar_h / 2)
    elif kind == "handles":
        painter.drawEllipse(QtCore.QPointF(cx - s * 0.18, cy), s * 0.20, s * 0.20)
        painter.drawEllipse(QtCore.QPointF(cx + s * 0.18, cy), s * 0.20, s * 0.20)
    elif kind == "uptime":
        painter.drawEllipse(QtCore.QPointF(cx, cy), h * 0.62, h * 0.62)
        painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx, cy - h * 0.34))
        painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx + h * 0.30, cy + h * 0.14))
    painter.restore()


class _IconBadge(QtWidgets.QWidget):
    """彩色圆角图标徽章：柔和的品牌色底 + 同色几何图标。"""

    def __init__(self, kind, accent, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._accent = QtGui.QColor(accent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _event):
        tc = _theme_colors()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QtGui.QColor(self._accent)
        bg.setAlpha(24)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, 10, 10)
        ring = QtGui.QColor(self._accent)
        ring.setAlpha(90)
        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(ring, 1))
        p.drawRoundedRect(rect, 10, 10)
        _paint_metric_icon(p, self.width() / 2, self.height() / 2,
                           min(self.width(), self.height()) - 7, self._kind, self._accent)
        p.end()


class _MetricCard(QtWidgets.QFrame):
    """资源指标卡片：图标徽章 + 标签 + 主色数值，左侧品牌色强调条。"""

    def __init__(self, label, accent, tc, kind, parent=None):
        super().__init__(parent)
        self.setObjectName("metric_card")
        self._accent = QtGui.QColor(accent)
        self.setStyleSheet(
            f"QFrame#metric_card {{ border: 1px solid {tc['card_border']}; border-radius: 9px;"
            f" background: {tc['card_bg']}; }}")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(9, 8, 10, 8)
        lay.setSpacing(10)
        lay.addWidget(_IconBadge(kind, accent, self))
        vb = QtWidgets.QVBoxLayout()
        vb.setSpacing(1)
        lb_label = BodyLabel(label, self)
        lb_label.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8.5pt;")
        self._value = StrongBodyLabel("--", self)
        self._value.setStyleSheet(f"color: {accent};")
        vb.addWidget(lb_label)
        vb.addWidget(self._value)
        lay.addLayout(vb)
        lay.addStretch(1)

    def set_value(self, text):
        self._value.setText(text)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        accent = QtGui.QColor(self._accent)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QtCore.QRectF(1.5, 5, 3, self.height() - 10), 1.5, 1.5)
        p.end()


def _make_metric_card(label, value_text, tc, parent, accent=None, icon_kind=None):
    """创建资源指标卡片。返回 (card, 数值 QLabel)。"""
    if accent is None:
        accent = tc.get("accent", "#1178e0")
    if icon_kind is None:
        icon_kind = "cpu"
    card = _MetricCard(label, accent, tc, icon_kind, parent)
    card.set_value(value_text)
    return card, card._value
