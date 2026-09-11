"""tests/test_perf_monitor_ui.py: 性能监测模块 UI 构建与功能测试。"""
import collections
import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _make_qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _make_owner():
    class _Ctx:
        def module_setting(self, mid, key, default):
            return default
        def set_module_config(self, mid, cfg):
            pass
    class _Owner:
        id = "performance_meter"
        context = _Ctx()
        _shared_cpu_data = collections.deque(maxlen=120)
        _shared_mem_data = collections.deque(maxlen=120)
        _shared_listeners = []
        def register_shared_listener(self, cb):
            self._shared_listeners.append(cb)
        def unregister_shared_listener(self, cb):
            try:
                self._shared_listeners.remove(cb)
            except ValueError:
                pass
    return _Owner()


# ── 页面构建 ──────────────────────────────────────────────────────────

def test_page_builds_without_error():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    assert w is not None


def test_page_has_group_boxes():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    groups = w.findChildren(QtWidgets.QGroupBox)
    titles = [g.title() for g in groups]
    assert "进程资源" in titles


def test_page_is_scrollable():
    """整个页面包裹在 QScrollArea 中，支持滚动。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    assert isinstance(w, QtWidgets.QScrollArea)
    assert w.widgetResizable()


def test_page_has_all_tabs():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tabs = w.findChildren(QtWidgets.QTabWidget)
    assert len(tabs) >= 1
    tab_texts = [tabs[0].tabText(i) for i in range(tabs[0].count())]
    for name in ("关键操作耗时统计", "函数采样器", "线程栈", "运行状态/卡死排查"):
        assert name in tab_texts


def test_tab_pane_background_transparent():
    """tab 面板不得叠加出不透明白板背景（避免米色/白色面板）。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tabs = w.findChildren(QtWidgets.QTabWidget)[0]
    assert "QTabWidget::pane" in tabs.styleSheet()
    assert "background: transparent" in tabs.styleSheet()


def test_no_manual_thread_snapshot_button():
    """线程栈不再有手动「抓取线程栈」按钮，改为自动刷新。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    buttons = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert not any("抓取线程栈" in t for t in buttons)


def test_page_has_tables():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    assert len(tables) == 2


def test_tables_sorting_enabled():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    for t in tables:
        assert t.isSortingEnabled()


def test_numeric_sort_uses_magnitude_not_string():
    """排序必须按数值大小，而非字符串（10 应大于 9）。"""
    _make_qapp()
    from modules.perf_monitor import _populate_table, _NumItem
    table = QtWidgets.QTableWidget()
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels(["名称", "次数"])
    table.setSortingEnabled(True)
    rows = [
        {"name": "a", "count": 997},
        {"name": "b", "count": 9},
        {"name": "c", "count": 10},
        {"name": "d", "count": 10000},
    ]
    _populate_table(table, rows, ["名称", "次数"], {0: "name", 1: "count"},
                    numeric_cols={1})
    table.sortItems(1, QtCore.Qt.SortOrder.DescendingOrder)
    order = [table.item(i, 0).text() for i in range(table.rowCount())]
    assert order == ["d", "a", "c", "b"]
    assert isinstance(table.item(0, 1), _NumItem)


def test_table_last_column_not_stretched():
    """最后一列不应被 stretch 拉得很大（耗时统计/采样器）。"""
    _make_qapp()
    from modules.perf_monitor import _make_perf_table, _theme_colors
    table = _make_perf_table(["名称", "次数", "总耗时", "耗时"], _theme_colors())
    assert not table.horizontalHeader().stretchLastSection()
    assert table.horizontalHeader().sectionResizeMode(3) == QtWidgets.QHeaderView.Interactive


def test_process_resources_reports_cpu():
    """进程资源监控返回完整指标，CPU 字段为数值。"""
    from modules.perf_monitor import _proc_resources
    r = _proc_resources()
    for k in ("pid", "cpu", "memory_mb", "threads", "handles", "uptime_s"):
        assert k in r
    assert isinstance(r["cpu"], (int, float))
    assert r["threads"] >= 1
    assert r["memory_mb"] > 0


def test_bar_text_color_contrast():
    """条形文字按亮度取黑/白，保证与条形的对比度。"""
    from modules.perf_monitor import _bar_text_color
    assert _bar_text_color(255, 255, 255) == "#0f0f0f"
    assert _bar_text_color(10, 10, 10) == "#ffffff"
    assert _bar_text_color(0, 180, 80) == "#ffffff"
    assert _bar_text_color(200, 160, 0) == "#0f0f0f"
    assert _bar_text_color(220, 60, 40) == "#ffffff"


def test_page_has_metric_cards():
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    cards = w.findChildren(QtWidgets.QFrame, "metric_card")
    assert len(cards) == 6


def test_stat_table_has_bar_delegate():
    """耗时统计表的操作列使用了 _BarDelegate。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget, _BarDelegate
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    stat_table = tables[0]
    delegate = stat_table.itemDelegateForColumn(0)
    assert isinstance(delegate, _BarDelegate)


def test_prof_table_has_bar_delegate():
    """函数采样器表的函数列使用了 _BarDelegate。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget, _BarDelegate
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    prof_table = tables[1]
    delegate = prof_table.itemDelegateForColumn(0)
    assert isinstance(delegate, _BarDelegate)


def test_no_standalone_profiler_button():
    """函数采样器没有独立的启动/停止按钮。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    from qfluentwidgets import SwitchButton
    switches = w.findChildren(SwitchButton)
    assert len(switches) == 1  # 只有采集开关


# ── BarDelegate ───────────────────────────────────────────────────────

def test_bar_delegate_set_max():
    _make_qapp()
    from modules.perf_monitor import _BarDelegate
    table = QtWidgets.QTableWidget()
    table.setColumnCount(3)
    table.setRowCount(1)
    delegate = _BarDelegate(table, bar_col=0, value_col=2)
    delegate.set_max(100.0)
    assert delegate._max_value == 100.0


def test_bar_delegate_set_max_zero():
    _make_qapp()
    from modules.perf_monitor import _BarDelegate
    table = QtWidgets.QTableWidget()
    table.setColumnCount(3)
    delegate = _BarDelegate(table)
    delegate.set_max(0.0)
    assert delegate._max_value >= 0.001


def test_bar_delegate_paint():
    _make_qapp()
    from modules.perf_monitor import _BarDelegate
    table = QtWidgets.QTableWidget()
    table.setColumnCount(3)
    table.setRowCount(1)
    table.setItem(0, 0, QtWidgets.QTableWidgetItem("test_op"))
    table.setItem(0, 2, QtWidgets.QTableWidgetItem("42.5"))
    table.item(0, 2).setData(QtCore.Qt.UserRole, 42.5)
    delegate = _BarDelegate(table, bar_col=0, value_col=2)
    delegate.set_max(100.0)
    table.show()
    table.repaint()


# ── 表格构建辅助 ──────────────────────────────────────────────────────

def test_make_perf_table():
    _make_qapp()
    from modules.perf_monitor import _make_perf_table, _theme_colors
    tc = _theme_colors()
    table = _make_perf_table(["A", "B", "C"], tc)
    assert table.columnCount() == 3
    assert table.isSortingEnabled()
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Interactive
    assert table._perf_locked_cols == set()
    assert table._perf_suppress_lock is False


def test_populate_table():
    _make_qapp()
    from modules.perf_monitor import _make_perf_table, _populate_table, _theme_colors
    tc = _theme_colors()
    table = _make_perf_table(["name", "count", "ms"], tc, col_widths={0: 100, 1: 60, 2: 60})
    rows = [
        {"name": "op_a", "count": 10, "ms": 5.5},
        {"name": "op_b", "count": 3, "ms": 1.2},
    ]
    col_keys = {0: "name", 1: "count", 2: "ms"}
    _populate_table(table, rows, ["name", "count", "ms"], col_keys, numeric_cols={1, 2})
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "op_a"
    assert table.item(0, 1).data(QtCore.Qt.UserRole) == 10.0


def test_populate_table_disables_sort_during_fill():
    _make_qapp()
    from modules.perf_monitor import _make_perf_table, _populate_table, _theme_colors
    tc = _theme_colors()
    table = _make_perf_table(["name", "val"], tc, col_widths={0: 100, 1: 60})
    rows = [{"name": "x", "val": 1}]
    _populate_table(table, rows, ["name", "val"], {0: "name", 1: "val"}, numeric_cols={1})
    assert table.isSortingEnabled()


# ── SortFilterProxy ───────────────────────────────────────────────────

def test_sort_filter_less_than_numeric():
    _make_qapp()
    from modules.perf_monitor import _SortFilterProxy
    model = QtGui.QStandardItemModel()
    item_a = QtGui.QStandardItem("a")
    item_a.setData(10.0, QtCore.Qt.UserRole)
    item_b = QtGui.QStandardItem("b")
    item_b.setData(20.0, QtCore.Qt.UserRole)
    model.appendRow(item_a)
    model.appendRow(item_b)
    proxy = _SortFilterProxy()
    proxy.setSourceModel(model)
    proxy.setSortRole(QtCore.Qt.UserRole)
    proxy.sort(0, QtCore.Qt.AscendingOrder)
    assert proxy.data(proxy.index(0, 0)) == "a"
    assert proxy.data(proxy.index(1, 0)) == "b"


# ── 主题样式辅助 ──────────────────────────────────────────────────────

def test_theme_colors_returns_dict():
    from modules.perf_monitor import _theme_colors
    tc = _theme_colors()
    for key in ("dark", "group_border", "group_bg", "card_bg", "text_primary",
                "text_secondary", "bar_colors", "grid_color", "sel_bg"):
        assert key in tc


def test_group_box_style_returns_string():
    from modules.perf_monitor import _group_box_style, _theme_colors
    tc = _theme_colors()
    s = _group_box_style(tc)
    assert "QGroupBox" in s
    assert "border-radius" in s


def test_table_style_returns_string():
    from modules.perf_monitor import _table_style, _theme_colors
    tc = _theme_colors()
    s = _table_style(tc)
    assert "QTableWidget" in s


# ── CPU 读数新鲜度（首次 0.0 / 长间隔窗口失效）────────────────────────

def test_proc_resources_first_call_guards_zero():
    """首次调用 cpu_percent 无基线返回 0.0，属无意义读数：仅建立基线，
    返回值沿用上次有效值（默认 0.0），不把 0.0 当作真实读数。"""
    import modules.perf_monitor.proc as proc_mod
    proc_mod._reset_cpu_state()
    r1 = proc_mod._proc_resources()
    assert r1["cpu"] == 0.0
    # 第二次调用为真实读数（数值即可，可能为 0 或 >0）
    r2 = proc_mod._proc_resources()
    assert isinstance(r2["cpu"], (int, float))


def test_proc_resources_long_gap_keeps_last_value():
    """定时器暂停（窗口隐藏）后恢复：cpu_percent 的读数跨度过大，
    应丢弃并沿用上次有效值；下一次调用即为新鲜读数。"""
    import time
    import modules.perf_monitor.proc as proc_mod
    proc_mod._reset_cpu_state()
    proc_mod._proc_resources()  # 建立基线
    # 模拟 60 秒长间隔（窗口隐藏期间定时器暂停）
    proc_mod._LAST_CPU_TS = time.monotonic() - 60.0
    proc_mod._LAST_CPU_VAL = 42.0
    r = proc_mod._proc_resources()
    assert r["cpu"] == 42.0  # 长间隔读数被丢弃，沿用上次有效值
    # 下一次调用间隔正常，返回新鲜读数
    r2 = proc_mod._proc_resources()
    assert isinstance(r2["cpu"], (int, float))


# ── 函数采样器暂停/恢复（行内编辑期间）────────────────────────────────

def test_profiler_pause_resume_cycle():
    """profile_pause/profile_resume 成对工作；显式 stop 后 resume 不复活。"""
    import core.perf as perf
    from core.perf import (profile_pause, profile_resume, profile_start,
                           profile_stop)
    profile_stop()
    assert perf._profiler_enabled is False
    # 未运行时 pause/resume 均为 no-op
    profile_pause()
    assert perf._profiler_enabled is False
    profile_resume()
    assert perf._profiler_enabled is False
    # 启动 → 暂停 → 恢复
    profile_start()
    assert perf._profiler_enabled is True
    profile_pause()
    assert perf._profiler_enabled is False
    assert perf._profiler_paused is True
    profile_resume()
    assert perf._profiler_enabled is True
    assert perf._profiler_paused is False
    # 显式停止后 resume 不得复活采样器
    profile_stop()
    assert perf._profiler_enabled is False
    profile_resume()
    assert perf._profiler_enabled is False
    profile_stop()  # 清理


def test_perf_module_default_disabled(tmp_path):
    """性能监测模块默认不开启耗时采集/函数采样器（sys.setprofile 开销）。"""
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    from core.perf import is_enabled
    from modules.perf_monitor.module import Module
    cfg = AppConfig(path=str(tmp_path / "settings.json"), defaults=DEFAULT_CONFIG)

    class _Ctx:
        def __init__(self, config):
            self.config = config

    mod = Module(_Ctx(cfg))
    mod.start()
    assert is_enabled() is False


def test_delegate_pauses_profiler_during_edit():
    """行内编辑期间函数采样器暂停，编辑结束恢复。"""
    _make_qapp()
    import core.perf as perf
    from core.perf import profile_start, profile_stop
    from modules.todo_notes.delegate import _TodoItemDelegate
    table = QtWidgets.QTableWidget()
    table.setColumnCount(2)
    table.setRowCount(1)
    delegate = _TodoItemDelegate(table)
    profile_start()
    try:
        assert perf._profiler_enabled is True
        opt = QtWidgets.QStyleOptionViewItem()
        editor = delegate.createEditor(table, opt, table.model().index(0, 1))
        assert perf._profiler_enabled is False  # 编辑中已暂停
        delegate.destroyEditor(editor, table.model().index(0, 1))
        assert perf._profiler_enabled is True   # 编辑结束已恢复
    finally:
        profile_stop()


# ── 任务组 2：owner 级共享数据 deque（跨页面保留历史）──────────────────

def _make_module():
    from modules.perf_monitor.module import Module

    class _Ctx:
        def module_setting(self, mid, key, default):
            return default
        def set_module_config(self, mid, cfg):
            pass
    return Module(_Ctx())


def test_module_has_shared_deques():
    """Module 初始化即创建 owner 级共享 deque，maxlen=120。"""
    mod = _make_module()
    assert mod._shared_cpu_data is not None
    assert mod._shared_mem_data is not None
    assert mod._shared_cpu_data.maxlen == 120
    assert mod._shared_mem_data.maxlen == 120


def test_shared_deque_drops_oldest_on_overflow():
    """共享 deque 溢出时丢弃最旧数据（maxlen 行为）。"""
    mod = _make_module()
    for i in range(130):
        mod._shared_cpu_data.append(float(i))
    assert len(mod._shared_cpu_data) == 120
    assert mod._shared_cpu_data[0] == 10.0   # 最旧的 10 条被丢弃
    assert mod._shared_cpu_data[-1] == 129.0


def test_shared_tick_appends_to_deques():
    """_shared_tick 采集资源并 append 到共享 deque。"""
    mod = _make_module()
    mod._shared_tick()
    assert len(mod._shared_cpu_data) == 1
    assert len(mod._shared_mem_data) == 1
    assert isinstance(mod._shared_cpu_data[0], (int, float))
    assert isinstance(mod._shared_mem_data[0], (int, float))


def test_page_charts_initialized_from_shared_deque():
    """页面图表从 owner 共享 deque 批量初始化历史数据。"""
    _make_qapp()
    from modules.perf_monitor import _LineChart, _make_page_widget
    mod = _make_module()
    for i in range(10):
        mod._shared_cpu_data.append(float(i))
        mod._shared_mem_data.append(float(i) * 2)
    w = _make_page_widget(mod, None)
    charts = w.findChildren(_LineChart)
    cpu_chart = next(c for c in charts if c._title == "CPU 占用 (%)")
    mem_chart = next(c for c in charts if c._title == "内存占用 (MB)")
    assert list(cpu_chart._data) == [float(i) for i in range(10)]
    assert list(mem_chart._data) == [float(i) * 2 for i in range(10)]


def test_page_chart_live_update_via_shared_listener():
    """页面图表通过 owner 共享监听实时更新。"""
    _make_qapp()
    from modules.perf_monitor import _LineChart, _make_page_widget
    mod = _make_module()
    w = _make_page_widget(mod, None)
    charts = w.findChildren(_LineChart)
    cpu_chart = next(c for c in charts if c._title == "CPU 占用 (%)")
    before = len(cpu_chart._data)
    mod._shared_tick()
    assert len(cpu_chart._data) == before + 1


def test_page_unregisters_shared_listener_on_destroy():
    """页面销毁后从 owner 监听列表移除，无 dangling 回调。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    mod = _make_module()
    w = _make_page_widget(mod, None)
    assert len(mod._shared_listeners) == 1
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert len(mod._shared_listeners) == 0


# ── 子进程崩溃隔离：打开→关闭→重新打开保留历史 ─────────────────────────

def test_page_reopen_retains_history_no_crash_subprocess():
    """Subprocess isolation: open→close→reopen page retains chart history (0xC0000005 guard)."""
    import subprocess
    from pathlib import Path
    child_name = "test_page_reopen_retains_history_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_perf_monitor_ui.py::{child_name}",
         "-q"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


def test_page_reopen_retains_history_no_crash_child():
    """Child: open→close→reopen perf page; re-created charts must retain shared-deque history.

    Crash mechanism: if the page's shared-listener callback survives page
    destruction (dangling reference), a later _shared_tick() calls push() on a
    freed C++ chart object → hard crash (0xC0000005) that except Exception
    cannot catch. Re-creating the page must also re-initialize charts from the
    owner's shared deque.
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from modules.perf_monitor import _LineChart, _make_page_widget
    from modules.perf_monitor.module import Module

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    class _Cfg:
        def module_setting(self, mid, key, default):
            return default
        def set_module_config(self, mid, cfg):
            pass
    class _Ctx:
        config = _Cfg()

    mod = Module(_Ctx())
    mod.start()

    # 第一次打开：共享定时器推入数据
    for _ in range(3):
        mod._shared_tick()
    w1 = _make_page_widget(mod, None)
    charts1 = w1.findChildren(_LineChart)
    cpu1 = next(c for c in charts1 if c._title == "CPU 占用 (%)")
    assert len(cpu1._data) == 3

    # 关闭页面：销毁并确认监听断开
    w1.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert len(mod._shared_listeners) == 0

    # 页面关闭期间共享采集继续
    for _ in range(2):
        mod._shared_tick()

    # 重新打开：图表从共享 deque 恢复历史
    w2 = _make_page_widget(mod, None)
    charts2 = w2.findChildren(_LineChart)
    cpu2 = next(c for c in charts2 if c._title == "CPU 占用 (%)")
    mem2 = next(c for c in charts2 if c._title == "内存占用 (MB)")
    assert list(cpu2._data) == list(mod._shared_cpu_data)
    assert list(mem2._data) == list(mod._shared_mem_data)
    assert len(cpu2._data) == 5  # 3 次开页前 + 2 次关页期间

    # 再次关闭，确认无 dangling 回调
    w2.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert len(mod._shared_listeners) == 0

    mod.stop()

    # 若走到这里，无崩溃发生
    print("PERF_PAGE_REOPEN_OK")
