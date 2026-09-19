"""win_maintenance 甘特式错误时间线图：纯 QPainter 渲染，零第三方图表依赖。

每个聚合组 = 一行水平条形；x 轴为时间，条形从 first_time 延伸到 last_time，
条形长度反映持续时长；颜色按日志级别取自 theme_palette 令牌。
"""
import datetime

from core.qt_bootstrap import import_qt
from core.theme.tokens import _s, rgba_to_qcolor, sizing, theme_palette

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

# 零时长条形的最小可见宽度（px）
_MIN_BAR_W = 4

# 标签列宽占画布宽度的比例（与 wp_timeline_label_width_min 取较大者）
_LABEL_WIDTH_RATIO = 0.28

# 标签列右缘拖拽手柄的半命中宽度（px）
_HANDLE_W = 6

# 拖拽时标签列允许占用的最大宽度 = 画布宽度 - 给绘图区的最小留白
_MIN_PLOT_RESERVE = 80

# 配置键：标签列宽持久化（真实 AppConfig 用 dot-path）
_LABEL_WIDTH_CONFIG_KEY = "win_maintenance.timeline_label_width"

# 画布顶部时间轴刻度区高度 / 底部留白（px 基线，随字体缩放）——
# 与 paintEvent 的 top/bottom 同源，set_groups 用它计算内容最小高度，
# 保证行数再多也不会触发 paintEvent 的 `y + row_h > h` 截断守卫。
_TIMELINE_TOP_PAD = _s(22)
_TIMELINE_BOTTOM_PAD = _s(6)


def _tooltip_text(g):
    """整行 tooltip 文本。

    聚合模式（含 children）：来源摘要 + 各子组 event_id/次数/消息首行；
    精确模式：来源 [事件ID] + 完整 message。
    """
    children = g.get("children")
    if children:
        lines = [f"{g['source']}（共 {g.get('count', 0)} 次）"]
        for c in children:
            msg = (c.get("message") or "").strip().splitlines()
            first = (msg[0][:120]) if msg else ""
            lines.append(f"  [{c.get('event_id')}] ×{c.get('count', 0)} {first}")
        return "\n".join(lines)
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

    def __init__(self, parent=None, config=None, config_key=None):
        super().__init__(parent)
        self._groups = []
        self._bar_rects = []  # [(group_index, QRectF)] 供测试/悬停命中
        self._row_rects = []  # [(group_index, QRectF)] 整行命中（D16）
        self._hover_index = -1
        self._label_w = None  # None=默认比例；拖拽/持久化后为固定值
        self._dragging = False
        self._config = config
        self._config_key = config_key or _LABEL_WIDTH_CONFIG_KEY
        if config is not None:
            try:
                saved = config.get(self._config_key)
                if isinstance(saved, (int, float)) and saved > 0:
                    self._label_w = int(float(saved))
            except (TypeError, ValueError):
                pass
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

    @property
    def label_width(self):
        """当前标签列宽（默认比例或拖拽/持久化后的固定值）。"""
        return self._effective_label_w()

    def _effective_label_w(self):
        if self._label_w is not None:
            return self._label_w
        sz = sizing()
        return max(sz["wp_timeline_label_width_min"],
                   int(self.width() * _LABEL_WIDTH_RATIO))

    @staticmethod
    def _color_for(tc, level):
        """级别 → 主题色 QColor（hex 直接 QColor，rgba 走 rgba_to_qcolor）。"""
        key = _LEVEL_COLOR_KEY.get(level, "wp_timeline_bar_bg")
        raw = tc.get(key, tc["wp_timeline_bar_bg"])
        return rgba_to_qcolor(raw) if raw.startswith("rgba") else QtGui.QColor(raw)

    def _handle_hit(self, x):
        """x 是否命中标签列右缘拖拽手柄。"""
        lw = self._effective_label_w()
        return lw - _HANDLE_W <= x <= lw + _HANDLE_W

    def _font(self, size=7.5, bold=False):
        f = QtGui.QFont(self.font())
        f.setPointSizeF(size)
        f.setBold(bold)
        return f

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and \
                self._handle_hit(int(event.position().x())):
            self._dragging = True
            self.setCursor(QtGui.QCursor(QtCore.Qt.SizeHorCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, "position") else event.pos()

        if self._dragging:
            min_w = sizing()["wp_timeline_label_width_min"]
            max_w = max(min_w, self.width() - _MIN_PLOT_RESERVE)
            self._label_w = int(max(min_w, min(pos.x(), max_w)))
            self.update()
            return

        old = self._hover_index
        self._hover_index = -1
        for i, rect in self._row_rects:
            if rect.contains(pos):
                self._hover_index = i
                break
        if self._hover_index != old:
            self.update()
        # 悬停手柄区显示可拖拽光标
        if self._handle_hit(int(pos.x())):
            self.setCursor(QtGui.QCursor(QtCore.Qt.SizeHorCursor))
        else:
            self.unsetCursor()
        if 0 <= self._hover_index < len(self._groups):
            g = self._groups[self._hover_index]
            gp = event.globalPosition() if hasattr(event, "globalPosition") \
                else event.globalPos()
            _show_tooltip(self, gp.toPoint(), _tooltip_text(g))
        else:
            QtWidgets.QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._dragging:
            self._dragging = False
            self.unsetCursor()
            if self._config is not None:
                try:
                    self._config.set(self._config_key, int(self._effective_label_w()))
                except (TypeError, ValueError):
                    pass
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, _event):
        self._hover_index = -1
        self._dragging = False
        self.unsetCursor()
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

        label_w = self._effective_label_w()
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
        grid_pen = QtGui.QPen(rgba_to_qcolor(tc["wp_timeline_grid"]), 1)
        axis_pen = QtGui.QPen(rgba_to_qcolor(tc["wp_timeline_axis"]), 1)
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
        track_brush = rgba_to_qcolor(tc["wp_timeline_track"])
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

            def _bar_for(t0, t1, y_off, height):
                """子条矩形：时间区间 → x 坐标/宽度。"""
                s = (t0 - t_min).total_seconds() / total_sec
                e = (t1 - t_min).total_seconds() / total_sec
                x = left + s * plot_w
                bw = max((e - s) * plot_w, _MIN_BAR_W)
                return QtCore.QRectF(x, y + y_off, bw, max(height, 1))

            children = g.get("children")
            if children:
                # 聚合模式：行内垂直均分子条，同级别用明度梯度区分
                n = len(children)
                sub_h = (row_h - 8) / n
                for ci, c in enumerate(children):
                    c_f = _parse_time(c["first_time"])
                    c_l = _parse_time(c["last_time"])
                    if c_f is None or c_l is None:
                        continue
                    bar_rect = _bar_for(c_f, c_l, 4 + ci * sub_h, sub_h - 2)
                    color = self._color_for(tc, c.get("level", ""))
                    if n > 1:
                        color = color.lighter(100 + 20 * ci)  # 同级别明度区分
                    if idx == self._hover_index:
                        color.setAlpha(min(color.alpha() + 50, 255))
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(color)
                    p.drawRoundedRect(bar_rect, bar_r, bar_r)
                    self._bar_rects.append((idx, bar_rect))
            else:
                # 精确模式：单条形
                bar_x = left + start_ratio * plot_w
                bar_w = max((end_ratio - start_ratio) * plot_w, _MIN_BAR_W)
                bar_rect = QtCore.QRectF(bar_x, y + 4, bar_w, row_h - 8)
                color = self._color_for(tc, g.get("level", ""))
                if idx == self._hover_index:
                    color.setAlpha(min(color.alpha() + 50, 255))
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(bar_rect, bar_r, bar_r)
                self._bar_rects.append((idx, bar_rect))

            # 两行标签：上行 来源（聚合模式：来源[N 类]），下行 message 首行摘要
            if children:
                line1 = f"{g['source']}（{len(children)} 类）"
                line2 = (children[0].get("message") or "").splitlines()[0]
            else:
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