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
    """构造最小 owner 对象，模拟 Module 实例。"""
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
    """页面 widget 可正常创建，不崩溃。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    assert w is not None


def test_page_has_group_boxes():
    """页面包含「进程资源」「关键操作耗时统计」「函数级监测」三个 QGroupBox。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    groups = w.findChildren(QtWidgets.QGroupBox)
    titles = [g.title() for g in groups]
    assert "进程资源" in titles
    assert "关键操作耗时统计" in titles
    assert "函数级监测" in titles


def test_page_has_tables():
    """页面包含 2 个 QTableWidget（耗时统计 + 函数采样器）。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    assert len(tables) == 2


def test_tables_sorting_enabled():
    """两个表格都启用了排序。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    tables = w.findChildren(QtWidgets.QTableWidget)
    for t in tables:
        assert t.isSortingEnabled()


def test_page_has_bar_charts():
    """页面包含 2 个 _BarChartWidget（耗时统计 + 函数采样器）。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget, _BarChartWidget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    charts = w.findChildren(_BarChartWidget)
    assert len(charts) == 2


def test_page_has_metric_cards():
    """进程资源区包含 6 个指标卡片。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    cards = w.findChildren(QtWidgets.QFrame, "metric_card")
    assert len(cards) == 6


def test_page_has_chart_sort_controls():
    """耗时统计区包含排序/显示数量 ComboBox。"""
    _make_qapp()
    from modules.perf_monitor import _make_page_widget
    owner = _make_owner()
    w = _make_page_widget(owner, None)
    from qfluentwidgets import ComboBox
    combos = w.findChildren(ComboBox)
    # 至少有：刷新间隔 + 排序方式 + 显示数量 + （函数采样器内无额外的）
    assert len(combos) >= 3


# ── 条形图组件 ────────────────────────────────────────────────────────

def test_bar_chart_empty():
    """空数据不崩溃。"""
    _make_qapp()
    from modules.perf_monitor import _BarChartWidget
    chart = _BarChartWidget()
    chart.set_data([])
    chart.resize(400, 200)
    chart.show()
    assert chart._data == []


def test_bar_chart_set_data():
    """设置数据后 _data 和 _max_value 正确。"""
    _make_qapp()
    from modules.perf_monitor import _BarChartWidget
    chart = _BarChartWidget()
    data = [("op_a", 10.0), ("op_b", 5.0), ("op_c", 1.0)]
    chart.set_data(data)
    assert len(chart._data) == 3
    assert chart._max_value == 10.0


def test_bar_chart_limits_to_30():
    """超过 30 条数据只保留前 30。"""
    _make_qapp()
    from modules.perf_monitor import _BarChartWidget
    chart = _BarChartWidget()
    data = [(f"op_{i}", float(i)) for i in range(50)]
    chart.set_data(data)
    assert len(chart._data) == 30


def test_bar_chart_paint():
    """设置数据后可正常绘制不崩溃。"""
    _make_qapp()
    from modules.perf_monitor import _BarChartWidget
    chart = _BarChartWidget()
    chart.set_data([("fast_op", 0.1), ("slow_op", 5.0), ("mid_op", 1.0)])
    chart.resize(500, 200)
    chart.show()
    # 触发 paintEvent
    chart.repaint()


# ── 排序功能 ──────────────────────────────────────────────────────────

def test_sortable_item_with_role():
    """_make_sortable_item 带 numeric_value 时 UserRole 有值且右对齐。"""
    _make_qapp()
    from modules.perf_monitor import _make_sortable_item
    item = _make_sortable_item("42.5", 42.5)
    assert item.data(QtCore.Qt.UserRole) == 42.5
    assert item.text() == "42.5"


def test_sortable_item_without_role():
    """_make_sortable_item 无 numeric_value 时 UserRole 为 None。"""
    _make_qapp()
    from modules.perf_monitor import _make_sortable_item
    item = _make_sortable_item("hello")
    assert item.data(QtCore.Qt.UserRole) is None
    assert item.text() == "hello"


def test_table_sort_by_numeric_column():
    """表格按数值列排序后行顺序正确。"""
    _make_qapp()
    from modules.perf_monitor import _make_sortable_item
    table = QtWidgets.QTableWidget()
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels(["name", "value"])
    table.setSortingEnabled(True)
    rows = [("c", 3.0), ("a", 1.0), ("b", 2.0)]
    table.setRowCount(len(rows))
    for i, (name, val) in enumerate(rows):
        table.setItem(i, 0, _make_sortable_item(name))
        table.setItem(i, 1, _make_sortable_item(str(val), val))
    # 按 value 列升序排序
    table.sortByColumn(1, QtCore.Qt.AscendingOrder)
    names = [table.item(i, 0).text() for i in range(table.rowCount())]
    assert names == ["a", "b", "c"]


# ── 主题样式辅助 ──────────────────────────────────────────────────────

def test_theme_colors_returns_dict():
    """_theme_colors 返回包含必要键的字典。"""
    from modules.perf_monitor import _theme_colors
    tc = _theme_colors()
    for key in ("dark", "group_border", "group_bg", "card_bg", "text_primary",
                "text_secondary", "bar_colors", "grid_color", "sel_bg"):
        assert key in tc


def test_group_box_style_returns_string():
    """_group_box_style 返回非空 QSS 字符串。"""
    from modules.perf_monitor import _group_box_style, _theme_colors
    tc = _theme_colors()
    s = _group_box_style(tc)
    assert "QGroupBox" in s
    assert "border-radius" in s


def test_table_style_returns_string():
    """_table_style 返回包含 QTableWidget 的 QSS。"""
    from modules.perf_monitor import _table_style, _theme_colors
    tc = _theme_colors()
    s = _table_style(tc)
    assert "QTableWidget" in s
