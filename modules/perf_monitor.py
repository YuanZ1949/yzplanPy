"""perf_monitor 模块：YZplan 自身进程性能监测 + 关键操作耗时统计。

功能：
  - 进程资源面板：本进程 CPU / 内存 / 线程数 / 句柄数，可开关定时刷新。
  - 关键操作耗时统计：配合 core.perf 记录，按名称聚合均值/最大值等。
  - 热点函数条形图：直观展示耗时分布。
  - 导出 CSV / 清空 / 开关耗时采集。
  - 表格列头排序。

作为普通模块注册，提供 create_page（独立监测面板）与 create_home_widget（主页精简卡片）。
"""

import os
import threading
import time

from .base import ModuleBase
from core.qt_bootstrap import import_qt

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
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "card_bg": "rgba(255,255,255,0.06)",
            "card_border": "rgba(255,255,255,0.10)",
            "ctrl_bg": "rgba(255,255,255,0.05)",
            "ctrl_border": "rgba(255,255,255,0.10)",
            "grid_color": "rgba(255,255,255,0.08)",
            "sel_bg": "rgba(0,120,215,0.25)",
            "text_primary": "#e6e6e6",
            "text_secondary": "#999999",
            "accent": "rgba(0,120,215,0.6)",
            "bar_colors": [
                (0, 180, 80),    # 绿
                (60, 170, 50),   # 黄绿
                (180, 160, 0),   # 黄
                (220, 120, 0),   # 橙
                (220, 60, 40),   # 红
            ],
        }
    return {
        "dark": False,
        "group_border": "rgba(0,0,0,0.10)",
        "group_bg": "rgba(0,0,0,0.02)",
        "card_bg": "rgba(0,0,0,0.03)",
        "card_border": "rgba(0,0,0,0.08)",
        "ctrl_bg": "rgba(0,0,0,0.03)",
        "ctrl_border": "rgba(0,0,0,0.08)",
        "grid_color": "rgba(0,0,0,0.08)",
        "sel_bg": "rgba(0,120,215,0.18)",
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "accent": "rgba(0,120,215,0.8)",
        "bar_colors": [
            (34, 160, 70),
            (70, 150, 40),
            (200, 160, 0),
            (210, 110, 0),
            (210, 50, 30),
        ],
    }


def _group_box_style(tc):
    return (
        f"QGroupBox {{ border: 1px solid {tc['group_border']}; border-radius: 8px;"
        f" background: {tc['group_bg']}; margin-top: 14px; padding: 8px 6px 6px 6px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;"
        f" left: 12px; top: 2px; padding: 0 6px; color: {tc['text_primary']}; }}"
    )


def _card_frame_style(tc):
    return (
        f"QFrame#card {{ border: 1px solid {tc['card_border']}; border-radius: 8px;"
        f" background: {tc['card_bg']}; }}"
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
        f"QTableWidget::item {{ padding: 2px 4px; }}"
        f"QTableWidget::item:selected {{ background: {tc['sel_bg']}; }}"
        "QTableWidget::item:hover { background: transparent; }"
        "QTableWidget::item:selected:hover { background: " + tc['sel_bg'] + "; }"
    )


# ── 进程资源读取 ──────────────────────────────────────────────────────

def _proc_resources():
    import psutil
    p = psutil.Process()
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

def _make_metric_card(label, value_text, tc, parent):
    """创建单个指标卡片：标题 + 数值，带圆角边框。"""
    from qfluentwidgets import BodyLabel, StrongBodyLabel

    card = QtWidgets.QFrame(parent)
    card.setObjectName("metric_card")
    card.setStyleSheet(
        f"QFrame#metric_card {{ border: 1px solid {tc['card_border']}; border-radius: 8px;"
        f" background: {tc['card_bg']}; }}"
    )
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(10, 6, 10, 6)
    lay.setSpacing(2)

    lb_label = BodyLabel(label, card)
    lb_label.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 9pt;")
    lay.addWidget(lb_label)

    lb_val = StrongBodyLabel(value_text, card)
    lb_val.setStyleSheet(f"color: {tc['text_primary']};")
    lay.addWidget(lb_val)

    return card, lb_val


# ── 条形图组件 ────────────────────────────────────────────────────────

class _BarChartWidget(QtWidgets.QWidget):
    """水平条形图，用 QPainter 手绘，无需外部依赖。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []       # [(name, value)]
        self._max_value = 1.0
        self.setMinimumHeight(100)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Preferred)

    def set_data(self, data):
        """data: [(name, value)] 已排序，value 越大越靠前。"""
        self._data = data[:30]
        self._max_value = max((v for _, v in self._data), default=1.0) or 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        tc = _theme_colors()
        colors = tc["bar_colors"]

        w = self.width()
        h = self.height()
        n = len(self._data)
        if n == 0:
            painter.end()
            return

        fm = painter.fontMetrics()
        left_margin = 10
        right_margin = 10
        label_width = min(180, max(80, w // 4))
        bar_area_left = left_margin + label_width + 8
        bar_area_right = w - right_margin
        bar_area_w = max(1, bar_area_right - bar_area_left)

        row_h = max(22, min(28, (h - 8) // max(1, n)))
        total_h = n * row_h
        y_start = max(0, (h - total_h) // 2)

        for i, (name, value) in enumerate(self._data):
            y = y_start + i * row_h

            # 标签
            display_name = name if len(name) <= 28 else name[:25] + "..."
            painter.setPen(QtGui.QColor(tc["text_primary"]))
            label_rect = QtCore.QRect(left_margin, y, label_width, row_h)
            painter.drawText(label_rect,
                             int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight | QtCore.Qt.AlignAbsolute),
                             display_name)

            # 条
            ratio = value / self._max_value if self._max_value > 0 else 0
            bar_w = max(2, int(bar_area_w * ratio))
            bar_rect = QtCore.QRect(bar_area_left, y + 3, bar_w, row_h - 6)

            # 颜色梯度
            ci = int(ratio * (len(colors) - 1))
            ci = min(ci, len(colors) - 1)
            r, g, b = colors[ci]
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(r, g, b, 180))
            painter.drawRoundedRect(bar_rect, 3, 3)

            # 数值
            val_str = f"{value:.2f}" if isinstance(value, float) else str(value)
            painter.setPen(QtGui.QColor(tc["text_secondary"]))
            val_rect = QtCore.QRect(bar_area_left + bar_w + 6, y, 80, row_h)
            painter.drawText(val_rect,
                             int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                             val_str)

        painter.end()


# ── 主页精简卡片 ─────────────────────────────────────────────────────

def _make_home_widget(owner, parent):
    from qfluentwidgets import BodyLabel, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 8, 8, 8)
    lay.setSpacing(6)

    StrongBodyLabel("性能监测")
    lb = BodyLabel("CPU: --%   内存: -- MB  线程: --", w)
    lay.addWidget(lb)
    py = BodyLabel("进程: --", w)
    lay.addWidget(py)

    timer = QtCore.QTimer()
    timer.setInterval(2000)

    def _tick():
        try:
            r = _proc_resources()
            lb.setText(f"CPU: {r['cpu']:.0f}%   内存: {r['memory_mb']:.0f} MB   "
                       f"线程: {r['threads']}")
            py.setText(f"进程 PID: {r['pid']}  运行 {r['uptime_s'] // 60} 分钟")
        except Exception:
            pass

    timer.timeout.connect(_tick)
    timer.start()

    def _cleanup():
        try:
            timer.stop()
        except RuntimeError:
            pass
    w.destroyed.connect(_cleanup)

    def refresh():
        _tick()
    owner._perf_home_refresh = refresh
    _tick()
    return w


# ── 独立页面 ─────────────────────────────────────────────────────────

def _make_sortable_item(text, numeric_value=None):
    """创建表格 item，数字列额外存 UserRole 以便排序。"""
    item = QtWidgets.QTableWidgetItem(str(text))
    if numeric_value is not None:
        item.setData(QtCore.Qt.UserRole, float(numeric_value))
        item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter
                              | QtCore.Qt.AlignmentFlag.AlignRight
                              | QtCore.Qt.AlignmentFlag.AlignAbsolute)
    return item


def _make_page_widget(owner, parent):
    from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton, StrongBodyLabel, SwitchButton

    import core.perf as perf
    tc = _theme_colors()

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(10)

    # ── 控制行（卡片包裹）──────────────────────────────────────────
    ctrl_frame = QtWidgets.QFrame(w)
    ctrl_frame.setObjectName("ctrl")
    ctrl_frame.setStyleSheet(_ctrl_frame_style(tc))
    ctrl = QtWidgets.QHBoxLayout(ctrl_frame)
    ctrl.setContentsMargins(12, 8, 12, 8)
    ctrl.setSpacing(10)

    lb_enable = BodyLabel("采集耗时统计", w)
    ctrl.addWidget(lb_enable)
    sw_enable = SwitchButton()
    sw_enable.setChecked(perf.is_enabled())
    ctrl.addWidget(sw_enable)

    ctrl.addSpacing(16)
    lb_interval = BodyLabel("刷新间隔(秒):", w)
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

    # ── 进程资源（指标卡片）────────────────────────────────────────
    res_group = QtWidgets.QGroupBox("进程资源")
    res_group.setStyleSheet(_group_box_style(tc))
    res_lay = QtWidgets.QVBoxLayout(res_group)
    res_lay.setContentsMargins(12, 8, 12, 8)
    res_lay.setSpacing(6)

    metrics_frame = QtWidgets.QFrame(w)
    metrics_frame.setStyleSheet(f"QFrame {{ background: transparent; border: none; }}")
    metrics_lay = QtWidgets.QHBoxLayout(metrics_frame)
    metrics_lay.setContentsMargins(0, 0, 0, 0)
    metrics_lay.setSpacing(8)

    metric_cards = {}
    for key, label in [("pid", "PID"), ("cpu", "CPU"), ("memory", "内存 MB"),
                        ("threads", "线程"), ("handles", "句柄"), ("uptime", "运行时间")]:
        card, lb_val = _make_metric_card(label, "--", tc, w)
        metric_cards[key] = lb_val
        metrics_lay.addWidget(card)

    res_lay.addWidget(metrics_frame)
    lb_res_note = BodyLabel("仅监测 YZplan 自身进程，非整机资源", w)
    lb_res_note.setStyleSheet(f"color: {tc['text_secondary']}; font-size: 8pt;")
    res_lay.addWidget(lb_res_note)
    lay.addWidget(res_group)

    # ── 关键操作耗时统计（表格 + 条形图）───────────────────────────
    stat_group = QtWidgets.QGroupBox("关键操作耗时统计")
    stat_group.setStyleSheet(_group_box_style(tc))
    stat_lay = QtWidgets.QVBoxLayout(stat_group)
    stat_lay.setContentsMargins(12, 8, 12, 8)
    stat_lay.setSpacing(8)

    table = QtWidgets.QTableWidget()
    table.setColumnCount(7)
    table.setHorizontalHeaderLabels(
        ["操作", "次数", "总耗时(ms)", "平均(ms)", "最大(ms)", "最小(ms)", "最近(ms)"])
    table.setSortingEnabled(True)
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(table)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(_table_style(tc))
    stat_lay.addWidget(table, 2)

    # 耗时条形图
    chart_sort_combo = ComboBox()
    chart_sort_combo.addItem("按平均耗时", userData="avg")
    chart_sort_combo.addItem("按总耗时", userData="total")
    chart_sort_combo.addItem("按调用次数", userData="count")
    chart_sort_combo.setMinimumWidth(100)

    chart_limit_combo = ComboBox()
    chart_limit_combo.addItem("Top 10", userData=10)
    chart_limit_combo.addItem("Top 15", userData=15)
    chart_limit_combo.addItem("全部", userData=9999)
    chart_limit_combo.setCurrentIndex(1)
    chart_limit_combo.setMinimumWidth(80)

    chart_ctrl = QtWidgets.QHBoxLayout()
    chart_ctrl.addWidget(BodyLabel("热点分布:", w))
    chart_ctrl.addWidget(chart_sort_combo)
    chart_ctrl.addWidget(BodyLabel("显示:", w))
    chart_ctrl.addWidget(chart_limit_combo)
    chart_ctrl.addStretch(1)
    stat_lay.addLayout(chart_ctrl)

    bar_chart = _BarChartWidget(w)
    bar_chart.setMinimumHeight(120)
    bar_chart.setMaximumHeight(250)
    stat_lay.addWidget(bar_chart, 1)

    lay.addWidget(stat_group, 2)

    # ── 函数级监测（QTabWidget）────────────────────────────────────
    from core.perf import profile_snapshot, profile_start, profile_stop, thread_snapshots

    fgrp = QtWidgets.QGroupBox("函数级监测")
    fgrp.setStyleSheet(_group_box_style(tc))
    flay = QtWidgets.QVBoxLayout(fgrp)
    flay.setContentsMargins(12, 8, 12, 8)

    tabs = QtWidgets.QTabWidget()

    # 页1：采样器热点（表格 + 条形图）
    tab_prof = QtWidgets.QWidget()
    tp = QtWidgets.QVBoxLayout(tab_prof)
    tp.setContentsMargins(4, 6, 4, 4)

    prof_ctrl = QtWidgets.QHBoxLayout()
    sw_prof = SwitchButton()
    sw_prof.setChecked(perf._profiler_enabled if hasattr(perf, "_profiler_enabled") else False)
    prof_ctrl.addWidget(BodyLabel("启用函数采样器", tab_prof))
    prof_ctrl.addWidget(sw_prof)
    btn_snap = PushButton("立即快照")
    prof_ctrl.addWidget(btn_snap)
    prof_ctrl.addStretch(1)
    tp.addLayout(prof_ctrl)

    prof_table = QtWidgets.QTableWidget()
    prof_table.setColumnCount(3)
    prof_table.setHorizontalHeaderLabels(["函数", "调用次数", "自用耗时(s)"])
    prof_table.setSortingEnabled(True)
    make_adaptive_table(prof_table)
    prof_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    prof_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    prof_table.setAlternatingRowColors(True)
    prof_table.verticalHeader().setVisible(False)
    prof_table.setStyleSheet(_table_style(tc))
    tp.addWidget(prof_table, 2)

    # 函数采样器条形图
    prof_chart = _BarChartWidget(tab_prof)
    prof_chart.setMinimumHeight(80)
    prof_chart.setMaximumHeight(180)
    tp.addWidget(prof_chart, 1)

    def _refresh_profiler():
        rows = profile_snapshot()
        prof_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            prof_table.setItem(i, 0, _make_sortable_item(r["name"]))
            prof_table.setItem(i, 1, _make_sortable_item(str(r["count"]), r["count"]))
            prof_table.setItem(i, 2, _make_sortable_item(f"{r['self_s']:.4f}", r["self_s"]))
        # 更新条形图
        chart_data = [(r["name"].split(" ", 1)[-1] if " " in r["name"] else r["name"],
                       r["self_s"]) for r in rows if r["self_s"] > 0]
        chart_data.sort(key=lambda x: x[1], reverse=True)
        prof_chart.set_data(chart_data[:15])

    def _on_prof_toggle(on):
        if on:
            perf.profile_start()
        else:
            perf.profile_stop()
        _refresh_profiler()

    sw_prof.checkedChanged.connect(_on_prof_toggle)
    btn_snap.clicked.connect(_refresh_profiler)

    # 页2：线程栈快照
    tab_thr = QtWidgets.QWidget()
    tt = QtWidgets.QVBoxLayout(tab_thr)
    tt.setContentsMargins(4, 6, 4, 4)
    thr_ctrl = QtWidgets.QHBoxLayout()
    btn_stack = PushButton("抓取线程栈")
    thr_ctrl.addWidget(btn_stack)
    thr_ctrl.addStretch(1)
    tt.addLayout(thr_ctrl)
    stack_list = QtWidgets.QListWidget()
    stack_list.setStyleSheet(
        "QListWidget { border: none; background: transparent; }"
        "QListWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    tt.addWidget(stack_list, 1)

    def _refresh_threads():
        stack_list.clear()
        for t in thread_snapshots():
            head = f"线程 {t['thread_id']}"
            if t["stack"]:
                head += f"  →  {t['stack'][-1]}"
            stack_list.addItem(head)
            for depth, fn in enumerate(t["stack"]):
                stack_list.addItem(("    " * (depth + 1)) + fn)
        stack_list.addItem(f"共 {len(thread_snapshots())} 个线程")

    btn_stack.clicked.connect(_refresh_threads)

    # 页3：运行状态 / 卡死排查（飞行记录器）
    tab_watch = QtWidgets.QWidget()
    tw = QtWidgets.QVBoxLayout(tab_watch)
    tw.setContentsMargins(4, 6, 4, 4)
    wstatus = BodyLabel("", tab_watch)
    tw.addWidget(wstatus)
    wstack = QtWidgets.QPlainTextEdit()
    wstack.setReadOnly(True)
    wstack.setStyleSheet(
        "QPlainTextEdit { border: 1px solid rgba(128,128,128,0.2); border-radius: 5px;"
        " background: rgba(128,128,128,0.08); color: inherit; font-family: Consolas, monospace;}")
    tw.addWidget(wstack, 1)
    btn_wrefresh = PushButton("刷新")
    btn_wopen = PushButton("打开磁盘记录")
    wctrl = QtWidgets.QHBoxLayout()
    wctrl.addWidget(btn_wrefresh)
    wctrl.addWidget(btn_wopen)
    wctrl.addStretch(1)
    tw.addLayout(wctrl)

    def _refresh_watch():
        from core.perf import main_thread_signal, read_disk_signal, watchdog_alive
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

    btn_wrefresh.clicked.connect(_refresh_watch)
    btn_wopen.clicked.connect(_open_disk)

    tabs.addTab(tab_prof, "函数采样器")
    tabs.addTab(tab_thr, "线程栈")
    tabs.addTab(tab_watch, "运行状态/卡死排查")
    flay.addWidget(tabs, 1)
    lay.addWidget(fgrp, 2)

    lb_status = BodyLabel("", w)
    lb_status.setStyleSheet(f"color: {tc['text_secondary']};")
    lay.addWidget(lb_status)

    # ── 定时器与刷新 ──────────────────────────────────────────────
    _res_timer = QtCore.QTimer()

    def _on_page_destroyed():
        try:
            _res_timer.stop()
        except RuntimeError:
            pass
        if getattr(perf, "_profiler_enabled", False) and not sw_prof.isChecked():
            try:
                perf.profile_stop()
            except Exception:
                pass
    w.destroyed.connect(_on_page_destroyed)

    def _refresh_resources():
        try:
            r = _proc_resources()
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
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            table.setItem(i, 0, _make_sortable_item(r["name"]))
            table.setItem(i, 1, _make_sortable_item(str(r["count"]), r["count"]))
            table.setItem(i, 2, _make_sortable_item(f"{r['total_ms']:.1f}", r["total_ms"]))
            table.setItem(i, 3, _make_sortable_item(f"{r['avg_ms']:.2f}", r["avg_ms"]))
            table.setItem(i, 4, _make_sortable_item(f"{r['max_ms']:.2f}", r["max_ms"]))
            table.setItem(i, 5, _make_sortable_item(f"{r['min_ms']:.2f}", r["min_ms"]))
            table.setItem(i, 6, _make_sortable_item(f"{r['last_ms']:.2f}", r["last_ms"]))
        table.setSortingEnabled(True)

        # 更新条形图
        sort_by = chart_sort_combo.currentData()
        limit = chart_limit_combo.currentData()
        _update_bar_chart(rows, sort_by, limit)

        lb_status.setText(f"共 {len(rows)} 个已采集操作   上次导出: -")

    def _update_bar_chart(rows, sort_by, limit):
        if sort_by == "avg":
            chart_data = [(r["name"], r["avg_ms"]) for r in rows if r["avg_ms"] > 0]
        elif sort_by == "total":
            chart_data = [(r["name"], r["total_ms"]) for r in rows if r["total_ms"] > 0]
        else:
            chart_data = [(r["name"], float(r["count"])) for r in rows if r["count"] > 0]
        chart_data.sort(key=lambda x: x[1], reverse=True)
        bar_chart.set_data(chart_data[:limit])

    def _on_chart_sort_changed():
        rows = perf.stats()
        sort_by = chart_sort_combo.currentData()
        limit = chart_limit_combo.currentData()
        _update_bar_chart(rows, sort_by, limit)

    chart_sort_combo.currentIndexChanged.connect(_on_chart_sort_changed)
    chart_limit_combo.currentIndexChanged.connect(_on_chart_sort_changed)

    def _on_interval_changed():
        _res_timer.setInterval(int(combo_interval.currentData()) * 1000)
        _res_timer.start()

    combo_interval.currentIndexChanged.connect(_on_interval_changed)

    def _on_enable_changed(on):
        owner.context.config.set_module_config(owner.id, {"enabled": bool(on)})
        perf.set_enabled(bool(on))
        if not on:
            table.setRowCount(0)
            bar_chart.set_data([])
            lb_status.setText("耗时采集已关闭")

    _res_timer.timeout.connect(_refresh_resources)
    _res_timer.timeout.connect(_refresh_stats)
    _res_timer.setInterval(2000)
    _res_timer.start()

    def _export():
        try:
            path = perf.export_csv()
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success("已导出", f"已导出到:\n{path}", parent=w,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
            lb_status.setText(f"共 {len(perf.stats())} 个已采集操作   已导出到 {path}")
        except Exception as e:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("导出失败", str(e), parent=w,
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

    _refresh_resources()
    _refresh_stats()
    owner._perf_page_refresh = _refresh_stats
    return w
