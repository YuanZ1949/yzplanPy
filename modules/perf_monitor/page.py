"""perf_monitor 独立页面：_make_page_widget（单函数原子切片，超 250 行豁免）。"""
import time
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import (_ctrl_frame_style, _group_box_style, _tabs_style,
                     _theme_colors)
from .cards import _make_metric_card
from .chart import _LineChart
from .bar import _BarDelegate
from .table import _make_perf_table, _populate_table
from .proc import _proc_resources
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
        "QPlainTextEdit { border: 1px solid rgba(128,128,128,0.2); border-radius: 6px;"
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
        _res_timer.setInterval(int(combo_interval.currentData() or 2) * 1000)
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
