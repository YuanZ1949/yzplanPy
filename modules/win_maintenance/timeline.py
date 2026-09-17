"""win_maintenance 甘特式错误时间线图：纯 QPainter 渲染，零第三方图表依赖。

每个聚合组 = 一行水平条形；x 轴为时间，条形从 first_time 延伸到 last_time，
条形长度反映持续时长；颜色按日志级别取自 theme_palette 令牌。
"""
import datetime

from core.qt_bootstrap import import_qt
from core.theme.tokens import _s, sizing, theme_palette

_, QtCore, QtGui, QtWidgets = import_qt()

# 级别 → theme_palette 令牌 key（颜色全部来自令牌，禁止硬编码 hex）
_LEVEL_COLOR_KEY = {
    "信息": "log_info",
    "成功": "log_info",
    "警告": "log_warning",
    "错误": "log_error",
    "失败": "log_error",
    "Critical": "log_critical",
}

# 时间范围选项（秒）
_RANGE_SECONDS = {"1h": 3600, "24h": 86400, "7d": 604800}
_RANGE_ORDER = ("1h", "24h", "7d")

# 零时长条形的最小可见宽度（px）
_MIN_BAR_W = 4

# 标签列宽占画布宽度的比例（与 wp_timeline_label_width_min 取较大者）
_LABEL_WIDTH_RATIO = 0.28

# 画布顶部时间轴刻度区高度 / 底部留白（px 基线，随字体缩放）——
# 与 paintEvent 的 top/bottom 同源，set_groups 用它计算内容最小高度，
# 保证行数再多也不会触发 paintEvent 的 `y + row_h > h` 截断守卫。
_TIMELINE_TOP_PAD = _s(22)
_TIMELINE_BOTTOM_PAD = _s(6)


def _tooltip_text(g):
    """整行 tooltip 文本：来源 [事件ID] + 完整 message。"""
    return f"{g['source']} [{g['event_id']}]\n{g.get('message', '')}"


def _elide_label(fm, text, width):
    """按标签列宽省略文本（右省略号）。"""
    return fm.elidedText(text, QtCore.Qt.ElideRight, width)


def _show_tooltip(widget, global_pos, text):
    """显示 tooltip（独立 seam，供测试拦截）。"""
    QtWidgets.QToolTip.showText(global_pos, text, widget)


def _parse_time(s):
    """时间字符串 → datetime；解析失败返回 None。"""
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


class _ChartWidget(QtWidgets.QWidget):
    """纯 QPainter 甘特图区域：网格 + 时间轴刻度 + 行标签 + 级别色条形 + 悬停提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups = []
        self._bar_rects = []  # [(group_index, QRectF)] 供测试/悬停命中
        self._row_rects = []  # [(group_index, QRectF)] 整行命中（D16）
        self._hover_index = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(sizing()["log_table_min_height"])

    def set_groups(self, groups):
        self._groups = groups or []
        self._bar_rects = []
        self._row_rects = []
        self._hover_index = -1
        self._update_min_height()
        self.update()

    def _update_min_height(self):
        """内容最小高度 = 顶部刻度区 + n×行高 + 底部留白（不低于表格兜底高度）。

        高度随组数增长：组数再多时 QScrollArea 出现滚动条而非截断行。
        """
        sz = sizing()
        n = len(self._groups)
        row_h = sz["wp_timeline_row_height"]
        content_h = _TIMELINE_TOP_PAD + n * row_h + _TIMELINE_BOTTOM_PAD
        self.setMinimumHeight(max(sz["log_table_min_height"], content_h))

    @property
    def bar_rects(self):
        return list(self._bar_rects)

    @property
    def row_rects(self):
        return list(self._row_rects)

    def _font(self, size=7.5, bold=False):
        f = QtGui.QFont(self.font())
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()
        old = self._hover_index
        self._hover_index = -1
        for i, rect in self._row_rects:
            if rect.contains(pos):
                self._hover_index = i
                break
        if self._hover_index != old:
            self.update()
        if 0 <= self._hover_index < len(self._groups):
            g = self._groups[self._hover_index]
            gp = event.globalPosition() if hasattr(event, "globalPosition") \
                else event.globalPos()
            _show_tooltip(self, gp.toPoint(), _tooltip_text(g))
        else:
            QtWidgets.QToolTip.hideText()

    def leaveEvent(self, _event):
        self._hover_index = -1
        self.update()
        QtWidgets.QToolTip.hideText()

    def paintEvent(self, _event):
        tc = theme_palette()
        sz = sizing()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # 不透明画布：QTabWidget::pane 背景透明，必须自绘实色底防透出
        p.fillRect(self.rect(), QtGui.QColor(tc["wp_timeline_bg"]))
        w, h = self.width(), self.height()
        if w <= 60 or h <= 40:
            p.end()
            return

        label_w = max(sz["wp_timeline_label_width_min"],
                      int(w * _LABEL_WIDTH_RATIO))
        row_h = sz["wp_timeline_row_height"]
        bar_r = sz["wp_timeline_bar_radius"]
        left = label_w + 8
        top = _TIMELINE_TOP_PAD
        right = 14
        bottom = _TIMELINE_BOTTOM_PAD
        plot_w = w - left - right

        self._bar_rects = []
        self._row_rects = []

        if not self._groups:
            p.setFont(self._font(8))
            p.setPen(QtGui.QColor(tc["text_secondary"]))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "无数据")
            p.end()
            return

        # ── 时间范围：全部组 first/last 的并集 ──
        times = []
        for g in self._groups:
            f = _parse_time(g["first_time"])
            l = _parse_time(g["last_time"])
            if f is not None:
                times.append(f)
            if l is not None:
                times.append(l)
        if not times:
            p.setFont(self._font(8))
            p.setPen(QtGui.QColor(tc["text_secondary"]))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "无数据")
            p.end()
            return
        t_min = min(times)
        t_max = max(times)
        if t_max <= t_min:
            t_max = t_min + datetime.timedelta(minutes=5)
        total_sec = max((t_max - t_min).total_seconds(), 1.0)

        # ── 网格与 x 轴刻度 ──
        n_ticks = max(2, min(8, plot_w // 100))
        grid_pen = QtGui.QPen(QtGui.QColor(tc["wp_timeline_grid"]), 1)
        axis_pen = QtGui.QPen(QtGui.QColor(tc["wp_timeline_axis"]), 1)
        for i in range(n_ticks + 1):
            x = left + plot_w * i / n_ticks
            p.setPen(grid_pen)
            p.drawLine(int(x), top, int(x), h - bottom)
            t_dt = t_min + datetime.timedelta(seconds=total_sec * i / n_ticks)
            label = t_dt.strftime("%m-%d %H:%M")
            p.setFont(self._font(7))
            p.setPen(axis_pen)
            p.drawText(int(x - 34), 2, 68, 16,
                       int(QtCore.Qt.AlignCenter), label)

        # ── 行标签 + 条形 ──
        label_pen = QtGui.QPen(QtGui.QColor(tc["text_secondary"]), 1)
        track_brush = QtGui.QColor(tc["wp_timeline_track"])
        fm = QtGui.QFontMetrics(self._font(7))
        for idx, g in enumerate(self._groups):
            y = top + idx * row_h
            if y + row_h > h:
                break
            self._row_rects.append((idx, QtCore.QRectF(0, y, w, row_h)))

            # 轨道背景
            track = QtCore.QRectF(left, y + 2, plot_w, row_h - 4)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(track_brush)
            p.drawRoundedRect(track, bar_r, bar_r)

            # 条形：first_time → last_time
            f_dt = _parse_time(g["first_time"])
            l_dt = _parse_time(g["last_time"])
            if f_dt is None or l_dt is None:
                continue
            start_ratio = (f_dt - t_min).total_seconds() / total_sec
            end_ratio = (l_dt - t_min).total_seconds() / total_sec
            bar_x = left + start_ratio * plot_w
            bar_w = max((end_ratio - start_ratio) * plot_w, _MIN_BAR_W)
            bar_rect = QtCore.QRectF(bar_x, y + 4, bar_w, row_h - 8)

            level = g.get("level", "")
            key = _LEVEL_COLOR_KEY.get(level, "wp_timeline_bar_bg")
            color = QtGui.QColor(tc.get(key, tc["wp_timeline_bar_bg"]))
            if idx == self._hover_index:
                color.setAlpha(min(color.alpha() + 50, 255))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(bar_rect, bar_r, bar_r)
            self._bar_rects.append((idx, bar_rect))

            # 两行标签：上行 来源 [事件ID]，下行 message 首行摘要（均 elide）
            line1 = f"{g['source']} [{g['event_id']}]"
            msg = g.get("message") or ""
            line2 = msg.splitlines()[0] if msg else ""
            half = row_h // 2
            p.setFont(self._font(7))
            p.setPen(label_pen)
            p.drawText(QtCore.QRectF(4, y, label_w, half),
                       int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight),
                       _elide_label(fm, line1, label_w))
            p.drawText(QtCore.QRectF(4, y + half, label_w, row_h - half),
                       int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight),
                       _elide_label(fm, line2, label_w))
        p.end()


class _ErrorTimeline(QtWidgets.QWidget):
    """甘特式错误时间线：时间范围选择栏 + 纯 QPainter 图表。"""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._current_range = "24h"
        self._groups = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        from qfluentwidgets import BodyLabel
        bar.addWidget(BodyLabel("时间范围:"))
        self._range_buttons = {}
        for name in _RANGE_ORDER:
            btn = QtWidgets.QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(name == self._current_range)
            btn.clicked.connect(lambda _c=False, n=name: self._set_range(n))
            self._range_buttons[name] = btn
            bar.addWidget(btn)
        bar.addStretch(1)
        self._summary = BodyLabel("")
        bar.addWidget(self._summary)
        lay.addLayout(bar)

        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._chart = _ChartWidget(self._scroll)
        self._scroll.setWidget(self._chart)
        lay.addWidget(self._scroll, 1)

    @property
    def bar_rects(self):
        return self._chart.bar_rects

    def set_groups(self, groups):
        """直接设置组数据（测试用），绕过 store 刷新。"""
        self._groups = groups or []
        self._chart.set_groups(self._groups)

    def _set_range(self, name):
        self._current_range = name
        for n, btn in self._range_buttons.items():
            btn.setChecked(n == name)
        self._refresh()

    def _refresh(self):
        now = datetime.datetime.now()
        delta = datetime.timedelta(seconds=_RANGE_SECONDS[self._current_range])
        date_from = (now - delta).strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = self._store.aggregate_errors(date_from=date_from) or []
        except TypeError:
            rows = self._store.aggregate_errors() or []
        self._groups = rows
        self._chart.set_groups(self._groups)
        total = sum(g.get("count", 0) for g in self._groups)
        self._summary.setText(
            f"共 {len(self._groups)} 组 · 覆盖事件 {total} 次 · {self._current_range}")