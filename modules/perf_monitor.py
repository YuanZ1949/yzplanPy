"""perf_monitor 模块：YZplan 自身进程性能监测 + 关键操作耗时统计。

功能：
  - 实时曲线：CPU / 内存历史采样折线图（近 4 分钟，随刷新间隔滚动）。
  - 进程资源面板：本进程 CPU / 内存 / 线程数 / 句柄数，彩色图标卡片展示。
  - 关键操作耗时统计：配合 core.perf 记录，按名称聚合均值/最大值等。
  - 行内条形图：表格「操作」列内嵌水平条形图，直观展示耗时分布。
  - 导出 CSV / 清空 / 开关耗时采集。
  - 表格列头排序。

作为普通模块注册，提供 create_page（独立监测面板）与 create_home_widget（主页精简卡片）。
"""

import collections
import math
import re
import time

from .base import ModuleBase
from core.qt_bootstrap import import_qt

from qfluentwidgets import BodyLabel, StrongBodyLabel

_, QtCore, QtGui, QtWidgets = import_qt()

MODULE_INFO = {
    "id": "performance_meter",
    "name": "性能监测",
    "description": "监测 YZplan 进程资源占用与关键操作耗时，支持导出",
}

ENABLED_KEY = "performance.enabled"


class Module(ModuleBase):
    MODULE_ID = "performance_meter"
    MODULE_NAME = "性能监测"
    MODULE_DESCRIPTION = "监测 YZplan 进程资源占用与关键操作耗时，支持导出"
    ENABLED_BY_DEFAULT = True

    def start(self):
        super().start()
        from core.perf import set_enabled
        enabled = self.context.config.module_setting(self.id, "enabled", True)
        set_enabled(enabled)

    def stop(self):
        super().stop()

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)


# ── 主题样式辅助 ─────────────────────────────────────────────────────

def _theme_colors():
    from core.theme import resolve_dark
    dark = resolve_dark("auto")
    if dark:
        return {
            "dark": True,
            "accent": "#3aa6ff",
            "accent_pid": "#5b8cff",
            "accent_cpu": "#25c9a0",
            "accent_mem": "#a06bff",
            "accent_thr": "#ffab40",
            "accent_hdl": "#ff6b8a",
            "accent_uptime": "#4fd97a",
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "card_bg": "rgba(255,255,255,0.06)",
            "card_border": "rgba(255,255,255,0.10)",
            "ctrl_bg": "rgba(255,255,255,0.05)",
            "ctrl_border": "rgba(255,255,255,0.10)",
            "grid_color": "rgba(255,255,255,0.06)",
            "sel_bg": "rgba(0,120,215,0.25)",
            "text_primary": "#e6e6e6",
            "text_secondary": "#999999",
            "bar_colors": [
                (0, 180, 80),
                (60, 170, 50),
                (180, 160, 0),
                (220, 120, 0),
                (220, 60, 40),
            ],
        }
    return {
        "dark": False,
        "accent": "#1178e0",
        "accent_pid": "#4a77f5",
        "accent_cpu": "#12a582",
        "accent_mem": "#7c3aed",
        "accent_thr": "#e08a1e",
        "accent_hdl": "#e4506f",
        "accent_uptime": "#2f9e5a",
        "group_border": "rgba(0,0,0,0.10)",
        "group_bg": "rgba(0,0,0,0.02)",
        "card_bg": "rgba(0,0,0,0.03)",
        "card_border": "rgba(0,0,0,0.08)",
        "ctrl_bg": "rgba(0,0,0,0.03)",
        "ctrl_border": "rgba(0,0,0,0.08)",
        "grid_color": "rgba(0,0,0,0.06)",
        "sel_bg": "rgba(0,120,215,0.18)",
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "bar_colors": [
            (34, 160, 70),
            (70, 150, 40),
            (200, 160, 0),
            (210, 110, 0),
            (210, 50, 30),
        ],
    }


def _qcolor(css):
    """把 '#hex' 或 'rgba(r,g,b,a)' 等 CSS 颜色字符串解析为 QColor，失败时回退灰色。"""
    s = (css or "").strip()
    if s.startswith("#"):
        c = QtGui.QColor(s)
        return c if c.isValid() else QtGui.QColor(128, 128, 128)
    m = re.match(
        r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+)\s*)?\)", s)
    if m:
        c = QtGui.QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        a = m.group(4)
        if a is not None:
            alpha = float(a)
            c.setAlpha(int(alpha if alpha > 1 else alpha * 255))
        return c
    c = QtGui.QColor(s)
    return c if c.isValid() else QtGui.QColor(128, 128, 128)


def _nice_ceil(v):
    """把 y 轴上限取整到规整刻度（1 / 2 / 2.5 / 5 的 10 的幂次）。"""
    if v <= 0:
        return 10.0
    exp = math.floor(math.log10(v))
    base = 10.0 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * base:
            return m * base
    return 10.0 * base


def _smooth_path(points):
    """用三次贝塞尔把折线平滑成曲线（逐段以中点作控制点）。"""
    if not points:
        return QtGui.QPainterPath()
    path = QtGui.QPainterPath(points[0])
    if len(points) < 2:
        return path
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        c1 = QtCore.QPointF((p1.x() + p2.x()) / 2, p1.y())
        c2 = QtCore.QPointF((p1.x() + p2.x()) / 2, p2.y())
        path.cubicTo(c1, c2, p2)
    return path


def _group_box_style(tc):
    return (
        f"QGroupBox {{ border: 1px solid {tc['group_border']}; border-radius: 8px;"
        f" background: {tc['group_bg']}; margin-top: 14px; padding: 8px 6px 6px 6px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;"
        f" left: 12px; top: 2px; padding: 0 6px; color: {tc['text_primary']}; }}"
    )


def _ctrl_frame_style(tc):
    return (
        f"QFrame#ctrl {{ border: 1px solid {tc['ctrl_border']}; border-radius: 8px;"
        f" background: {tc['ctrl_bg']}; }}"
    )


def _table_style(tc):
    return (
        "QTableWidget { border: none; background: transparent;"
        f" gridline-color: {tc['grid_color']}; }}"
        "QTableWidget::item { padding: 2px 4px; }"
        f"QTableWidget::item:selected {{ background: {tc['sel_bg']}; }}"
        "QTableWidget::item:hover { background: transparent; }"
        f"QTableWidget::item:selected:hover {{ background: {tc['sel_bg']}; }}"
    )


def _tabs_style(tc):
    """统一标签页样式：下划线式选中态，面板透明。"""
    sec = tc["text_secondary"]
    pri = tc["text_primary"]
    accent = tc["accent"]
    return (
        "QTabWidget::pane { background: transparent; border: none; }"
        "QTabWidget::tab-bar { alignment: left; }"
        f"QTabBar::tab {{ background: transparent; color: {sec}; padding: 8px 16px;"
        " border: none; border-bottom: 2px solid transparent; }}"
        f"QTabBar::tab:hover {{ color: {pri}; }}"
        f"QTabBar::tab:selected {{ color: {pri}; font-weight: 600;"
        f" border-bottom: 2px solid {accent}; }}"
        "QTabWidget QWidget { background: transparent; }"
    )


# ── 进程资源读取 ──────────────────────────────────────────────────────

_PROC = None  # 复用的 psutil.Process 实例，保证 cpu_percent 能跨次计算


def _proc_resources():
    global _PROC
    import psutil
    if _PROC is None or _PROC.pid != psutil.Process().pid:
        _PROC = psutil.Process()
    p = _PROC
    mem = p.memory_info()
    return {
        "pid": p.pid,
        "cpu": p.cpu_percent(interval=None) if hasattr(p, "cpu_percent") else 0.0,
        "memory_mb": round(mem.rss / (1024 * 1024), 1),
        "threads": p.num_threads() if hasattr(p, "num_threads") else 0,
        "handles": _num_handles(p.pid),
        "uptime_s": int(time.time() - p.create_time()) if hasattr(p, "create_time") else 0,
    }


def _num_handles(pid):
    try:
        import win32process
        import win32api
        h = win32api.OpenProcess(0x0400, False, pid)
        try:
            return win32process.GetProcessHandleCount(h)[1]
        finally:
            win32api.CloseHandle(h)
    except Exception:
        return 0


# ── 资源指标卡片 ──────────────────────────────────────────────────────

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


# ── 行内条形图 Delegate ──────────────────────────────────────────────

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


class _SortFilterProxy(QtCore.QSortFilterProxyModel):
    """按 UserRole float 排序数值列，字符串列按文字排。"""

    def lessThan(self, left, right):
        lv = left.data(QtCore.Qt.UserRole)
        rv = right.data(QtCore.Qt.UserRole)
        if lv is not None and rv is not None:
            try:
                return float(lv) < float(rv)
            except (TypeError, ValueError):
                pass
        return super().lessThan(left, right)


# ── 实时曲线图 ────────────────────────────────────────────────────────

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


# ── 主页精简卡片 ─────────────────────────────────────────────────────

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


# ── 表格构建辅助 ─────────────────────────────────────────────────────

def _make_perf_table(headers, tc, col_widths=None):
    """创建统一风格的性能表格，带排序支持。
    - Interactive 模式：列宽可手动拖动调整，双击表头按内容适应。
    - col_widths: {col_index: pixels} 设定初始列宽（仅作起始值，仍可拖动）。
    用户手动拖动某列后，该列在自动刷新时保持手动宽度不再被内容覆盖。
    """
    table = QtWidgets.QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSortingEnabled(True)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(_table_style(tc))
    header = table.horizontalHeader()
    header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
    header.setStretchLastSection(False)
    table.setMinimumWidth(600)
    if col_widths:
        for c, w in col_widths.items():
            table.setColumnWidth(c, w)

    # 记录用户手动调整过的列，自动刷新时不再覆盖其宽度
    table._perf_locked_cols = set()
    table._perf_suppress_lock = False

    def _on_section_resized(col, _old, _new):
        try:
            if not table._perf_suppress_lock:
                table._perf_locked_cols.add(col)
        except Exception:
            pass

    header.sectionResized.connect(_on_section_resized)
    return table


class _NumItem(QtWidgets.QTableWidgetItem):
    """数值单元格：排序时按 UserRole 存的 float 数值比较（而非字符串）。"""

    def __lt__(self, other):
        try:
            lv = float(self.data(QtCore.Qt.UserRole))
            rv = float(other.data(QtCore.Qt.UserRole))
            return lv < rv
        except (TypeError, ValueError):
            return super().__lt__(other)


def _populate_table(table, rows, headers, col_keys, numeric_cols=None):
    """填充表格数据，排序安全：先禁用排序 → 填充 → 重启用。
    rows: list of dict。
    col_keys: {col_index: dict_key} 每列对应的 dict 键名。
    numeric_cols: set，需要设 UserRole + 右对齐的数值列索引集合。
    列宽：未手动拖过的列自动按内容适应；用户拖过的列保持手动宽度。
    """
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for i, r in enumerate(rows):
        for c, hdr in enumerate(headers):
            dk = col_keys.get(c, hdr)
            val = r.get(dk, "")
            text = str(val) if val is not None else ""
            if numeric_cols and c in numeric_cols:
                num_val = r.get(dk, 0)
                try:
                    fval = float(num_val) if num_val is not None else 0.0
                except (TypeError, ValueError):
                    fval = 0.0
                item = _NumItem(text)
                item.setData(QtCore.Qt.UserRole, fval)
                item.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignVCenter
                    | QtCore.Qt.AlignmentFlag.AlignRight
                    | QtCore.Qt.AlignmentFlag.AlignAbsolute)
            else:
                item = QtWidgets.QTableWidgetItem(text)
            table.setItem(i, c, item)
    table.setSortingEnabled(True)

    # 自适应列宽：跳过用户手动拖过的列，双击列头也可临时适应
    header = table.horizontalHeader()
    locked = getattr(table, "_perf_locked_cols", set())
    suppress = getattr(table, "_perf_suppress_lock", False)
    table._perf_suppress_lock = True
    try:
        for c in range(len(headers)):
            if c not in locked:
                table.resizeColumnToContents(c)
    finally:
        table._perf_suppress_lock = suppress


# ── 独立页面 ─────────────────────────────────────────────────────────

def _make_page_widget(owner, parent):
    from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton, SwitchButton

    import core.perf as perf
    tc = _theme_colors()

    # ── 整页放入滚动区 ────────────────────────────────────────
    w = QtWidgets.QScrollArea(parent)
    w.setWidgetResizable(True)
    w.setFrameShape(QtWidgets.QFrame.NoFrame)
    w.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    w.setMinimumWidth(700)
    # 整页绘制不透明的主题底色（QPalette.Window），
    # 避免半透明 QDialog 叠加桌面产生偏暖的米色发色。
    w.viewport().setAutoFillBackground(False)
    content = QtWidgets.QWidget()
    content.setAutoFillBackground(True)
    w.setWidget(content)
    lay = QtWidgets.QVBoxLayout(content)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)

    # ── 控制行 ──────────────────────────────────────────────────
    ctrl_frame = QtWidgets.QFrame(content)
    ctrl_frame.setObjectName("ctrl")
    ctrl_frame.setStyleSheet(_ctrl_frame_style(tc))
    ctrl = QtWidgets.QHBoxLayout(ctrl_frame)
    ctrl.setContentsMargins(12, 8, 12, 8)
    ctrl.setSpacing(10)

    lb_enable = BodyLabel("采集耗时统计（含函数采样器）", content)
    ctrl.addWidget(lb_enable)
    sw_enable = SwitchButton()
    sw_enable.setChecked(perf.is_enabled())
    ctrl.addWidget(sw_enable)

    ctrl.addSpacing(16)
    lb_interval = BodyLabel("刷新间隔(秒):", content)
    ctrl.addWidget(lb_interval)
    combo_interval = ComboBox()
    for sec in (1, 2, 5):
        combo_interval.addItem(f"{sec} 秒", userData=sec)
    combo_interval.setCurrentIndex(1)
    combo_interval.setMinimumWidth(80)
    ctrl.addWidget(combo_interval)
    ctrl.addStretch(1)

    btn_export = PrimaryPushButton("导出 CSV")
    ctrl.addWidget(btn_export)
    btn_clear = PushButton("清空")
    ctrl.addWidget(btn_clear)
    lay.addWidget(ctrl_frame)

    # ── 顶部一行：实时曲线（左，紧凑） + 进程资源（右，卡片堆积） ─────
    top_row = QtWidgets.QHBoxLayout()
    top_row.setSpacing(10)

    # 实时曲线：CPU / 内存 左右分布，整体左置、宽度收窄
    chart_group = QtWidgets.QGroupBox("实时曲线")
    chart_group.setStyleSheet(_group_box_style(tc))
    chart_lay = QtWidgets.QVBoxLayout(chart_group)
    chart_lay.setContentsMargins(12, 6, 12, 6)
    chart_lay.setSpacing(4)
    charts_row = QtWidgets.QHBoxLayout()
    charts_row.setSpacing(8)
    chart_cpu = _LineChart("CPU 占用 (%)", tc["accent_cpu"], "%", y_max=100.0)
    chart_mem = _LineChart("内存占用 (MB)", tc["accent_mem"], "MB", y_max=None)
    charts_row.addWidget(chart_cpu, 1)
    charts_row.addWidget(chart_mem, 1)
    chart_lay.addLayout(charts_row)
    chart_hint = BodyLabel("近 4 分钟采样 · 随上方刷新间隔滚动更新", content)
    chart_hint.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8pt;")
    chart_lay.addWidget(chart_hint)
    top_row.addWidget(chart_group, 5)

    # 进程资源：6 张指标卡片按 2×3 网格堆积
    res_group = QtWidgets.QGroupBox("进程资源")
    res_group.setStyleSheet(_group_box_style(tc))
    res_lay = QtWidgets.QVBoxLayout(res_group)
    res_lay.setContentsMargins(12, 6, 12, 6)
    res_lay.setSpacing(4)

    metric_specs = [
        ("pid", "PID", tc["accent_pid"], "pid"),
        ("cpu", "CPU", tc["accent_cpu"], "cpu"),
        ("memory", "内存 MB", tc["accent_mem"], "memory"),
        ("threads", "线程", tc["accent_thr"], "threads"),
        ("handles", "句柄", tc["accent_hdl"], "handles"),
        ("uptime", "运行时间", tc["accent_uptime"], "uptime"),
    ]
    metrics_grid = QtWidgets.QGridLayout()
    metrics_grid.setContentsMargins(0, 0, 0, 0)
    metrics_grid.setSpacing(8)
    metrics_grid.setColumnStretch(0, 1)
    metrics_grid.setColumnStretch(1, 1)
    metric_cards = {}
    for i, (key, label, accent, icon_kind) in enumerate(metric_specs):
        card, lb_val = _make_metric_card(label, "--", tc, content,
                                         accent=accent, icon_kind=icon_kind)
        metric_cards[key] = lb_val
        metrics_grid.addWidget(card, i // 2, i % 2)

    res_lay.addLayout(metrics_grid)
    lb_res_note = BodyLabel("仅监测 YZplan 自身进程，非整机资源", content)
    lb_res_note.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8pt;")
    res_lay.addWidget(lb_res_note)
    top_row.addWidget(res_group, 4)

    lay.addLayout(top_row)

    # ── 统一标签页：收纳全部功能 ────────────────────────────────
    from core.perf import profile_snapshot, profile_start, profile_stop, thread_snapshots

    tabs = QtWidgets.QTabWidget()
    tabs.setStyleSheet(_tabs_style(tc))
    tabs.setMinimumHeight(440)

    # 页1：关键操作耗时统计
    tab_stat = QtWidgets.QWidget()
    t_stat_lay = QtWidgets.QVBoxLayout(tab_stat)
    t_stat_lay.setContentsMargins(4, 6, 4, 4)

    STAT_HEADERS = ["操作", "次数", "总耗时(ms)", "平均(ms)", "最大(ms)", "最小(ms)", "最近(ms)"]
    stat_col_keys = {0: "name", 1: "count", 2: "total_ms", 3: "avg_ms",
                     4: "max_ms", 5: "min_ms", 6: "last_ms"}
    stat_numeric = {1, 2, 3, 4, 5, 6}

    stat_table = _make_perf_table(STAT_HEADERS, tc, col_widths={
        0: 220, 1: 70, 2: 100, 3: 90, 4: 90, 5: 90, 6: 90
    })
    stat_bar_delegate = _BarDelegate(stat_table, bar_col=0, value_col=2)
    stat_table.setItemDelegateForColumn(0, stat_bar_delegate)
    t_stat_lay.addWidget(stat_table, 1)
    tabs.addTab(tab_stat, "关键操作耗时统计")

    # 页2：函数采样器
    tab_prof = QtWidgets.QWidget()
    t_prof_lay = QtWidgets.QVBoxLayout(tab_prof)
    t_prof_lay.setContentsMargins(4, 6, 4, 4)

    PROF_HEADERS = ["函数", "调用次数", "自用耗时(s)"]
    prof_col_keys = {0: "name", 1: "count", 2: "self_s"}
    prof_numeric = {1, 2}

    prof_table = _make_perf_table(PROF_HEADERS, tc, col_widths={
        0: 300, 1: 90, 2: 120
    })
    prof_bar_delegate = _BarDelegate(prof_table, bar_col=0, value_col=2)
    prof_table.setItemDelegateForColumn(0, prof_bar_delegate)
    t_prof_lay.addWidget(prof_table, 1)
    tabs.addTab(tab_prof, "函数采样器")

    # ── 表格列宽跨会话记忆 ──────────────────────────────────────
    def _load_widths():
        try:
            cfg = getattr(getattr(owner, "context", None), "config", None)
            if cfg is None:
                return {}
            stored = cfg.module_setting(owner.id, "table_widths", {}) or {}
            return {k: v for k, v in stored.items() if isinstance(v, list)}
        except Exception:
            return {}

    def _apply_widths(table, key):
        widths = _load_widths().get(key)
        if not widths:
            return
        for col, wdt in enumerate(widths):
            if col >= table.columnCount():
                break
            try:
                wdt = int(wdt)
            except (TypeError, ValueError):
                continue
            if wdt < 20:
                continue
            table.setColumnWidth(col, wdt)
            table._perf_locked_cols.add(col)

    _save_timer = QtCore.QTimer()
    _save_timer.setSingleShot(True)
    _save_timer.setInterval(600)
    _dirty = {}

    def _flush_widths():
        saved = _load_widths()
        for key, table in (("stat", stat_table), ("prof", prof_table)):
            if _dirty.pop(key, False):
                saved[key] = [table.columnWidth(c) for c in range(table.columnCount())]
        try:
            cfg = getattr(getattr(owner, "context", None), "config", None)
            if cfg is not None:
                cfg.set_module_config(owner.id, {"table_widths": saved})
        except Exception:
            pass

    _save_timer.timeout.connect(_flush_widths)

    def _watch_width(key, table):
        header = table.horizontalHeader()

        def _on_resized(_col, _old, _new):
            if getattr(table, "_perf_suppress_lock", False):
                return
            _dirty[key] = True
            _save_timer.start()

        header.sectionResized.connect(_on_resized)

    _apply_widths(stat_table, "stat")
    _apply_widths(prof_table, "prof")
    _watch_width("stat", stat_table)
    _watch_width("prof", prof_table)
    w._perf_save_timer = _save_timer

    def _refresh_profiler():
        rows = profile_snapshot()
        _populate_table(prof_table, rows, PROF_HEADERS, prof_col_keys, prof_numeric)
        if rows:
            prof_bar_delegate.set_max(max(r["self_s"] for r in rows))

    # 页3：线程栈（自动随采样间隔刷新，紧凑行高）
    tab_thr = QtWidgets.QWidget()
    t_thr_lay = QtWidgets.QVBoxLayout(tab_thr)
    t_thr_lay.setContentsMargins(4, 6, 4, 4)

    thr_hint = BodyLabel("自动随上方采集间隔刷新", tab_thr)
    thr_hint.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8pt;")
    t_thr_lay.addWidget(thr_hint)

    stack_list = QtWidgets.QListWidget()
    stack_list.setFont(QtGui.QFont("Consolas", 8))
    stack_list.setSpacing(0)
    stack_list.setStyleSheet(
        "QListWidget { border: none; background: transparent; }"
        "QListWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    t_thr_lay.addWidget(stack_list, 1)
    tabs.addTab(tab_thr, "线程栈")

    def _refresh_threads():
        stack_list.clear()
        threads = thread_snapshots()
        for t in threads:
            head = f"线程 {t['thread_id']}"
            if t.get("main"):
                head += "  [主线程]"
            if t["stack"]:
                head += f"  →  {t['stack'][-1]}"
            elif t.get("native"):
                head += " （" + t.get("note", "原生线程") + "）"
            it = QtWidgets.QListWidgetItem(head)
            it.setSizeHint(QtCore.QSize(0, 18))
            stack_list.addItem(it)
            for depth, fn in enumerate(t["stack"]):
                cit = QtWidgets.QListWidgetItem(("    " * (depth + 1)) + fn)
                cit.setSizeHint(QtCore.QSize(0, 18))
                stack_list.addItem(cit)
        ft = QtWidgets.QListWidgetItem(f"共 {len(threads)} 个线程（含原生线程）")
        if len(threads) > 30:
            ft = QtWidgets.QListWidgetItem(
                f"共 {len(threads)} 个线程（含原生线程）。其中大部分为 QtWebEngine/Chromium "
                "浏览器进程线程池，首次 RSS 预览后产生，空闲时近 0 CPU，属于正常现象。")
        ft.setSizeHint(QtCore.QSize(0, 18))
        stack_list.addItem(ft)

    # 页4：运行状态 / 卡死排查
    tab_watch = QtWidgets.QWidget()
    tw = QtWidgets.QVBoxLayout(tab_watch)
    tw.setContentsMargins(4, 6, 4, 4)
    wstatus = BodyLabel("", tab_watch)
    tw.addWidget(wstatus)
    wstack = QtWidgets.QPlainTextEdit()
    wstack.setReadOnly(True)
    wstack.setFont(QtGui.QFont("Consolas", 8))
    wstack.setStyleSheet(
        "QPlainTextEdit { border: 1px solid rgba(128,128,128,0.2); border-radius: 5px;"
        " background: rgba(128,128,128,0.08); color: inherit; font-family: Consolas, monospace;}")
    tw.addWidget(wstack, 1)
    btn_wopen = PushButton("打开磁盘记录")
    wctrl = QtWidgets.QHBoxLayout()
    wctrl.addWidget(btn_wopen)
    wctrl.addStretch(1)
    tw.addLayout(wctrl)
    watch_hint = BodyLabel("状态与心跳随上方刷新间隔自动更新", tab_watch)
    watch_hint.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8pt;")
    tw.addWidget(watch_hint)
    tabs.addTab(tab_watch, "运行状态/卡死排查")

    lay.addWidget(tabs, 1)

    lb_status = BodyLabel("", content)
    lb_status.setStyleSheet(f"color: {tc['text_secondary']};")
    lay.addWidget(lb_status)

    # ── 定时器与刷新 ──────────────────────────────────────────
    _res_timer = QtCore.QTimer()

    def _on_page_destroyed():
        try:
            _res_timer.stop()
        except RuntimeError:
            pass
        if getattr(perf, "_profiler_enabled", False):
            try:
                perf.profile_stop()
            except Exception:
                pass
    w.destroyed.connect(_on_page_destroyed)

    def _refresh_resources():
        try:
            r = _proc_resources()
            chart_cpu.push(r["cpu"])
            chart_mem.push(r["memory_mb"])
            metric_cards["pid"].setText(str(r["pid"]))
            metric_cards["cpu"].setText(f"{r['cpu']:.0f}%")
            metric_cards["memory"].setText(f"{r['memory_mb']:.1f}")
            metric_cards["threads"].setText(str(r["threads"]))
            metric_cards["handles"].setText(str(r["handles"]))
            h = r["uptime_s"] // 3600
            m = (r["uptime_s"] % 3600) // 60
            metric_cards["uptime"].setText(f"{h}时{m}分")
        except Exception:
            for v in metric_cards.values():
                v.setText("--")

    def _refresh_stats():
        rows = perf.stats()
        _populate_table(stat_table, rows, STAT_HEADERS, stat_col_keys, stat_numeric)
        if rows:
            stat_bar_delegate.set_max(max(r["total_ms"] for r in rows))
        _refresh_profiler()
        _refresh_threads()
        lb_status.setText(f"共 {len(rows)} 个已采集操作")

    def _refresh_watch():
        from core.perf import heartbeat, main_thread_signal, watchdog_alive
        heartbeat()  # 并入模块刷新时钟：事件循环存活则心跳持续更新，卡死即暂停
        sig = main_thread_signal()
        hb = sig["heartbeat_ts"]
        last = sig["last_capture_ts"]
        hb_str = (time.strftime("%H:%M:%S", time.localtime(hb)) if hb else "（从未打点）")
        last_str = (time.strftime("%H:%M:%S", time.localtime(last)) if last else "—")
        sect = "✔ 守护线程运行中" if watchdog_alive() else "✘ 守护线程未运行"
        wstatus.setText(
            f"运行状态：{sect}\n"
            f"主线程最近心跳：{hb_str}（若卡死会停在此刻）    "
            f"最近抓栈：{last_str}   已缓存 {sig['captures']} 份\n"
            f"以下为最近一次抓到的『主线程』调用栈：")
        if sig["last_stack"]:
            wstack.setPlainText("\n".join(sig["last_stack"]))
        else:
            wstack.setPlainText("（暂无数据）")

    def _open_disk():
        from core.perf import read_disk_signal
        txt = read_disk_signal()
        if not txt:
            wstack.setPlainText("（磁盘上暂无记录）")
            return
        wstack.setPlainText(
            "以下为磁盘残留（上次运行留下的卡死线索，可能含更早的主线程栈）：\n\n" + txt)

    btn_wopen.clicked.connect(_open_disk)

    def _on_interval_changed():
        _res_timer.setInterval(int(combo_interval.currentData()) * 1000)
        _res_timer.start()

    combo_interval.currentIndexChanged.connect(_on_interval_changed)

    def _on_enable_changed(on):
        owner.context.config.set_module_config(owner.id, {"enabled": bool(on)})
        perf.set_enabled(bool(on))
        if on:
            if not getattr(perf, "_profiler_enabled", False):
                perf.profile_start()
        else:
            stat_table.setRowCount(0)
            prof_table.setRowCount(0)
            if getattr(perf, "_profiler_enabled", False):
                perf.profile_stop()
            lb_status.setText("耗时采集已关闭")

    _res_timer.timeout.connect(_refresh_resources)
    _res_timer.timeout.connect(_refresh_stats)
    _res_timer.timeout.connect(_refresh_watch)
    _res_timer.setInterval(2000)
    _res_timer.start()

    def _export():
        try:
            path = perf.export_csv()
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success("已导出", f"已导出到:\n{path}", parent=content,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
            lb_status.setText(f"共 {len(perf.stats())} 个已采集操作   已导出到 {path}")
        except Exception as e:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("导出失败", str(e), parent=content,
                          position=InfoBarPosition.TOP_RIGHT, duration=3000)

    def _clear():
        perf.reset()
        _refresh_stats()

    btn_export.clicked.connect(_export)
    btn_clear.clicked.connect(_clear)
    sw_enable.checkedChanged.connect(_on_enable_changed)

    def _cleanup():
        try:
            _res_timer.stop()
        except RuntimeError:
            pass
    w.destroyed.connect(_cleanup)

    # 初始化：如果开关开着则同时启动采样器
    if perf.is_enabled() and not getattr(perf, "_profiler_enabled", False):
        try:
            perf.profile_start()
        except Exception:
            pass

    # 卡死排查：若宿主（main.py）未启动守护线程，则由页面自行兜底启动，
    # 保证"运行状态/卡死排查"页打开时立即可用。
    # 心跳无需单独 QTimer：main.py 已全局 1s 打点，页面兜底场景则由
    # _refresh_watch 随模块刷新时钟打点（事件循环存活则持续更新）。
    try:
        if not perf.watchdog_alive():
            perf.start_watchdog()
    except Exception:
        pass

    _refresh_resources()
    _refresh_stats()
    _refresh_watch()
    owner._perf_page_refresh = _refresh_stats
    return w
