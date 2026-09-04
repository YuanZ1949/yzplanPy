"""tests/test_perf_monitor_ui.py: 性能监测模块 UI 构建与功能测试。"""
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
