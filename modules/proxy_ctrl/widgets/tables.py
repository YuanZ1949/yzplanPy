"""proxy_ctrl.widgets.tables：令牌化 QTableWidget 工厂 + 填充助手。

`ui/widgets.py` 没有表格工厂，这里补一个（`modules/perf_monitor/table.py` 与
`modules/router_admin/widgets/tables.py` 是同一模式的另外两份实现，本模块同样
自建，避免跨模块 UI 反向依赖）。所有 QSS 颜色取 `theme_palette()`、尺寸/字号取
`sizing()`，不写任何字面量。

表格内容全部来自**纯逻辑层**（scanner 的 ProxyCandidate、store 的历史条目、
targets 的目标对象），从不拼接用户输入到样式或命令里，因此无注入面。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette

from ui.widgets import make_status_chip, make_tool_button

_, QtCore, QtGui, QtWidgets = import_qt()

_AF = QtCore.Qt.AlignmentFlag          # PySide6 的对齐参数必须是枚举，不能是 int
_RIGHT = _AF.AlignVCenter | _AF.AlignRight
_CENTER = _AF.AlignVCenter | _AF.AlignCenter
_LEFT = _AF.AlignVCenter | _AF.AlignLeft
#: 最小宽度 = 基准 + 每列增量（纯布局下限，非视觉尺寸，不参与 QSS）
_TABLE_W_BASE = 60
_TABLE_W_PER_COL = 110
#: 表格最小高度（用 sizing 令牌派生，不写字面量）
_TABLE_MIN_H_KEY = "log_table_min_height"


def table_qss(p, sz):
    """表格 QSS：透明底 + 令牌网格线 + 令牌选中底。"""
    return (
        "QTableWidget { border: none; background: transparent;"
        f" gridline-color: {p['table_gridline']};"
        f" font-size: {sz['font_size_sm']}px; color: {p['text_primary']}; }}"
        f"QTableWidget::item {{ padding: {sz['qss_table_item_padding']};"
        f" color: {p['text_primary']}; }}"
        f"QTableWidget::item:selected {{ background: {p['table_sel_bg']};"
        f" color: {p['text_primary']}; }}"
        "QTableWidget::item:hover { background: transparent; }"
        f"QTableWidget::item:selected:hover {{ background: {p['table_sel_strong_bg']}; }}"
        "QHeaderView::section { background: transparent; border: none;"
        f" color: {p['text_secondary']}; font-size: {sz['font_size_xs']}px; }}"
    )


def make_table(headers, *, parent=None, min_height_key=_TABLE_MIN_H_KEY):
    """创建统一样式的只读表格。列宽可拖动，双击表头按内容自适应。"""
    sz = sizing()
    table = QtWidgets.QTableWidget(parent)
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(False)
    table.setSortingEnabled(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(table_qss(theme_palette(), sz))
    header = table.horizontalHeader()
    header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
    header.setStretchLastSection(True)
    table.setMinimumWidth(_TABLE_W_BASE +
                          _TABLE_W_PER_COL * max(0, len(headers) - 1))
    if min_height_key and min_height_key in sz:
        table.setMinimumHeight(sz[min_height_key])
    return table


class NumItem(QtWidgets.QTableWidgetItem):
    """数值单元格：排序按 UserRole 里的 float，而不是显示字符串。"""

    def __lt__(self, other):
        try:
            return float(self.data(QtCore.Qt.UserRole)) < float(
                other.data(QtCore.Qt.UserRole))
        except (TypeError, ValueError):
            return super().__lt__(other)


def fill_table(table, rows, columns, *, numeric=(), chips=None, align=None,
               action_col=None, actions=(), action_handler=None):
    """整表重填（先清空旧行与旧胶囊，再逐格写入）。

    columns: [(row_key, formatter_or_None), ...]，与表头列序一一对应。
    numeric: 数值列下标集合（按 UserRole 排序 + 右对齐）。
    chips:   {列下标: callable(row) -> (text, kind) | None}，该列渲染状态胶囊。
    action_col / actions / action_handler：操作列。`actions` 是
             [(按钮文字, callable(row) -> 参数), ...]，按钮在**排序重新启用之前**
             铺进单元格——否则 setSortingEnabled(True) 会重排行，按钮就与行错位。
    """
    rows = list(rows or [])
    table.setSortingEnabled(False)
    table.setRowCount(0)      # 归零：确保上一轮 setCellWidget 的胶囊被真正析构
    table.setRowCount(len(rows))
    chips = chips or {}
    align = align or {}
    for r, row in enumerate(rows):
        for c, spec in enumerate(columns):
            if c == action_col:
                buttons = [(text, build(row)) for text, build in actions]
                if buttons and action_handler is not None:
                    fill_action_cell(table, r, c, buttons, action_handler)
                continue
            key, fmt = spec if isinstance(spec, tuple) else (spec, None)
            value = row.get(key)
            if fmt is not None:
                text = fmt(value, row) if callable(fmt) else fmt(value)
            else:
                text = "" if value is None else str(value)
            if c in chips:
                made = chips[c](row)
                if made is None:
                    continue
                text, kind = made
                table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
                chip = make_status_chip(text, kind=kind, parent=table)
                chip.setAlignment(_CENTER)
                table.setCellWidget(r, c, chip)
            elif c in numeric:
                item = NumItem(text)
                try:
                    item.setData(QtCore.Qt.UserRole, float(value))
                except (TypeError, ValueError):
                    item.setData(QtCore.Qt.UserRole, 0.0)
                item.setTextAlignment(align.get(c, _RIGHT))
                table.setItem(r, c, item)
            else:
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(align.get(c, _LEFT))
                table.setItem(r, c, item)
    table.setSortingEnabled(True)


def fill_action_cell(table, row, col, actions, handler):
    """在单元格里铺一排工具按钮。actions: [(text, 参数), ...]。

    `handler(参数)` 在按钮被点击时于主线程调用。控件全部来自 make_tool_button，
    本函数不写任何样式。
    """
    box = QtWidgets.QWidget(table)
    lay = QtWidgets.QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(sizing()["radius_xs"])
    for text, arg in actions:
        btn = make_tool_button(text, size="sm", parent=box)
        btn.clicked.connect(lambda _=False, a=arg: handler(a))
        lay.addWidget(btn)
    lay.addStretch(1)
    table.setCellWidget(row, col, box)
    return box


def clear_table(table):
    """清空整表（含上一轮 setCellWidget 铺进去的按钮/胶囊）。"""
    table.setSortingEnabled(False)
    table.setRowCount(0)
    table.setSortingEnabled(True)
