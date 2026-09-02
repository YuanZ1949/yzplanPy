"""perf_monitor 模块：YZplan 自身进程性能监测 + 关键操作耗时统计。

功能：
  - 进程资源面板：本进程 CPU / 内存 / 线程数 / 句柄数，可开关定时刷新。
  - 关键操作耗时统计：配合 core.perf 记录，按名称聚合均值/最大值等。
  - 导出 CSV / 清空 / 开关耗时采集。

作为普通模块注册，提供 create_page（独立监测面板）与 create_home_widget（主页精简卡片）。
"""

import os
import threading
import time

from .base import ModuleBase

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


# ── 主页精简卡片 ─────────────────────────────────────────────────────

def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
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

def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton, SwitchButton

    import core.perf as perf

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    # 控制行
    ctrl = QtWidgets.QHBoxLayout()
    lb_enable = BodyLabel("采集耗时统计", w)
    ctrl.addWidget(lb_enable)
    sw_enable = SwitchButton()
    sw_enable.setChecked(perf.is_enabled())
    ctrl.addWidget(sw_enable)

    ctrl.addSpacing(20)
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
    lay.addLayout(ctrl)

    # 资源区
    res = QtWidgets.QGroupBox("进程资源")
    rlay = QtWidgets.QVBoxLayout(res)
    rlay.setContentsMargins(10, 10, 10, 10)
    rb = BodyLabel("", res)
    rlay.addWidget(rb)
    lay.addWidget(res)

    # 耗时统计表
    grp = QtWidgets.QGroupBox("关键操作耗时统计")
    glay = QtWidgets.QVBoxLayout(grp)
    glay.setContentsMargins(10, 10, 10, 10)
    table = QtWidgets.QTableWidget()
    table.setColumnCount(7)
    table.setHorizontalHeaderLabels(["操作", "次数", "总耗时(ms)", "平均(ms)", "最大(ms)", "最小(ms)", "最近(ms)"])
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(table)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { selection-background-color: rgba(128,128,128,0.15); }"
    )
    glay.addWidget(table, 1)
    lay.addWidget(grp, 1)

    # ── 函数级监测 ────────────────────────────────────────────────
    from core.perf import profile_snapshot, profile_start, profile_stop, thread_snapshots

    fgrp = QtWidgets.QGroupBox("函数级监测")
    flay = QtWidgets.QVBoxLayout(fgrp)
    flay.setContentsMargins(10, 10, 10, 10)

    tabs = QtWidgets.QTabWidget()

    # 页1：采样器热点
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
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(prof_table)
    prof_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    prof_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    prof_table.setAlternatingRowColors(True)
    prof_table.verticalHeader().setVisible(False)
    prof_table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    tp.addWidget(prof_table, 1)

    def _refresh_profiler():
        rows = profile_snapshot()
        prof_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            prof_table.setItem(i, 0, QtWidgets.QTableWidgetItem(r["name"]))
            prof_table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(r["count"])))
            prof_table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{r['self_s']:.4f}"))

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

    def _refresh_watch_tick():
        # 归一：仅当页面可见相关刷新
        _refresh_watch()

    btn_wrefresh.clicked.connect(_refresh_watch)
    btn_wopen.clicked.connect(_open_disk)

    tabs.addTab(tab_prof, "函数采样器")
    tabs.addTab(tab_thr, "线程栈")
    tabs.addTab(tab_watch, "运行状态/卡死排查")
    flay.addWidget(tabs, 1)
    lay.addWidget(fgrp, 1)

    lb_status = BodyLabel("", w)
    lay.addWidget(lb_status)

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
            rb.setText(
                f"PID: {r['pid']}   CPU: {r['cpu']:.0f}%   内存: {r['memory_mb']:.1f} MB   "
                f"线程: {r['threads']}   句柄: {r['handles']}   运行: {r['uptime_s'] // 3600}时 "
                f"{(r['uptime_s'] % 3600) // 60}分\n"
                f"（仅监测 YZplan 自身进程，非整机资源）"
            )
        except Exception:
            rb.setText("无法读取进程资源（可能需要权限）")

    def _refresh_stats():
        rows = perf.stats()
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            table.setItem(i, 0, QtWidgets.QTableWidgetItem(r["name"]))
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(str(r["count"])))
            table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{r['total_ms']:.1f}"))
            table.setItem(i, 3, QtWidgets.QTableWidgetItem(f"{r['avg_ms']:.2f}"))
            table.setItem(i, 4, QtWidgets.QTableWidgetItem(f"{r['max_ms']:.2f}"))
            table.setItem(i, 5, QtWidgets.QTableWidgetItem(f"{r['min_ms']:.2f}"))
            table.setItem(i, 6, QtWidgets.QTableWidgetItem(f"{r['last_ms']:.2f}"))
        lb_status.setText(f"共 {len(rows)} 个已采集操作   上次导出: -")

    def _on_interval_changed():
        _res_timer.setInterval(int(combo_interval.currentData()) * 1000)
        _res_timer.start()

    combo_interval.currentIndexChanged.connect(_on_interval_changed)

    def _on_enable_changed(on):
        owner.context.config.set_module_config(owner.id, {"enabled": bool(on)})
        perf.set_enabled(bool(on))
        if not on:
            table.setRowCount(0)
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
