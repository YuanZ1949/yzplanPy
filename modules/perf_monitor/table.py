"""perf_monitor 表格构建辅助：_make_perf_table/_NumItem/_populate_table。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .styles import _table_style
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
