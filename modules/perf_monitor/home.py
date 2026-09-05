"""perf_monitor 主页精简卡片：_HomePerfWidget/_make_home_widget。"""
import collections
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import _nice_ceil, _qcolor, _theme_colors
from .proc import _proc_resources
from .spark import _draw_spark
class _HomePerfWidget(QtWidgets.QWidget):
    """主页性能卡片：卡片底色 + CPU / 内存双迷你走势线 + 彩色数值。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._spark_cpu = collections.deque(maxlen=60)
        self._spark_mem = collections.deque(maxlen=60)
        self._cpu = 0.0
        self._mem = 0.0
        self._pid = "--"
        self._up_s = 0
        self.setMinimumSize(210, 150)

        self._timer = QtCore.QTimer()
        self._timer.setInterval(2000)

        def _tick():
            self._refresh()
        self._timer.timeout.connect(_tick)
        self._timer.start()
        self.destroyed.connect(self._stop_timer)

        def refresh():
            self._refresh()
        owner._perf_home_refresh = refresh
        self._refresh()

    def _stop_timer(self):
        try:
            self._timer.stop()
        except RuntimeError:
            pass

    def _refresh(self):
        try:
            r = _proc_resources()
            self._cpu = r["cpu"]
            self._mem = r["memory_mb"]
            self._pid = str(r["pid"])
            self._up_s = r["uptime_s"]
            self._spark_cpu.append(self._cpu)
            self._spark_mem.append(self._mem)
        except Exception:
            self._spark_cpu.append(0.0)
            self._spark_mem.append(0.0)
        self.update()

    def paintEvent(self, _event):
        tc = _theme_colors()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QtCore.QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QtGui.QPen(_qcolor(tc["card_border"]), 1))
        p.setBrush(_qcolor(tc["card_bg"]))
        p.drawRoundedRect(r, 11, 11)

        # ── 标题 ──
        p.setFont(self._font(9.5, bold=True))
        p.setPen(_qcolor(tc["text_primary"]))
        p.drawText(QtCore.QRectF(14, 8, w - 76, 20),
                   int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), "性能监测")
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(tc["accent_cpu"]))
        p.drawEllipse(QtCore.QPointF(w - 24, 18), 3.2, 3.2)
        p.setBrush(QtGui.QColor(tc["accent_mem"]))
        p.drawEllipse(QtCore.QPointF(w - 15, 18), 3.2, 3.2)

        # ── CPU 行 ──
        row_y = 40
        self._draw_row(p, tc, "CPU", row_y, self._cpu, "%",
                       self._spark_cpu, tc["accent_cpu"], w, 100.0)
        # ── 内存行 ──
        row_y = 72
        mem_max = _nice_ceil(max(self._spark_mem, default=0) or 64) if self._spark_mem else 64.0
        self._draw_row(p, tc, "内存", row_y, self._mem, "MB",
                       self._spark_mem, tc["accent_mem"], w, mem_max)

        # ── 页脚 ──
        up_h = self._up_s // 3600
        up_m = (self._up_s % 3600) // 60
        if up_h:
            uptime = f"{up_h}时{up_m}分"
        else:
            uptime = f"{up_m} 分钟"
        p.setPen(QtGui.QColor(tc["text_secondary"]))
        p.setFont(self._font(7.5))
        p.drawText(QtCore.QRectF(14, h - 26, w - 28, 16),
                   int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                   f"PID {self._pid}   ·   已运行 {uptime}")
        p.end()

    def _draw_row(self, p, tc, name, row_y, v, unit, spark, color, w, y_max):
        name_rect = QtCore.QRectF(14, row_y, 42, 24)
        p.setFont(self._font(8))
        p.setPen(QtGui.QColor(tc["text_secondary"]))
        p.drawText(name_rect, int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), name)

        spark_rect = QtCore.QRectF(62, row_y + 2, w - 62 - 96, 22)
        _draw_spark(p, spark_rect, list(spark), color, max(y_max, 0.001))

        p.setFont(self._font(8.5, bold=True))
        p.setPen(QtGui.QColor(color))
        p.drawText(QtCore.QRectF(w - 92, row_y, 78, 24),
                   int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight), f"{v:.0f} {unit}".strip())

    def _font(self, size=8, bold=False):
        f = QtGui.QFont(self.font())
        f.setPointSizeF(size)
        f.setBold(bold)
        return f


def _make_home_widget(owner, parent):
    return _HomePerfWidget(owner, parent)
