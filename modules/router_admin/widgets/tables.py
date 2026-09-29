"""router_admin.widgets.tables：令牌化 QTableWidget 工厂 + 表格区块复合控件。

`ui/widgets.py` 没有表格工厂，这里补一个。所有 QSS 颜色取 theme_palette()、
尺寸/字号取 sizing()，不写任何字面量（`perf_monitor.styles._table_style` 是
perf 私有样式，本模块不复用，改为引用全局 `table_gridline` / `table_sel_bg` 等令牌）。

本文件里的控件与样式都由**纯逻辑层驱动**（服务名、备份路径等都来自 parsers /
backup，绝不来自用户输入），因此不存在命令注入面。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette

from ui.widgets import make_button, make_label, make_status_chip, make_tool_button

from . import alert, confirm, notify

_, QtCore, QtGui, QtWidgets = import_qt()

_AF = QtCore.Qt.AlignmentFlag          # PySide6 的对齐参数必须是枚举，不能是 int
_RIGHT = _AF.AlignVCenter | _AF.AlignRight | _AF.AlignAbsolute
_CENTER = _AF.AlignVCenter | _AF.AlignCenter
_LEFT = _AF.AlignVCenter | _AF.AlignLeft
#: 最小宽度 = 基准 + 每列增量（纯布局下限，非视觉尺寸，不参与 QSS）
_TABLE_W_BASE = 60
_TABLE_W_PER_COL = 110


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


def make_table(headers, *, parent=None, min_height=0):
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
    if min_height:
        table.setMinimumHeight(min_height)
    return table


class NumItem(QtWidgets.QTableWidgetItem):
    """数值单元格：排序按 UserRole 里的 float，而不是显示字符串。"""

    def __lt__(self, other):
        try:
            return float(self.data(QtCore.Qt.UserRole)) < float(
                other.data(QtCore.Qt.UserRole))
        except (TypeError, ValueError):
            return super().__lt__(other)


def fill_table(table, rows, columns, *, numeric=(), chips=None, payload=None,
               align=None):
    """整表重填（先清空旧行与旧胶囊，再逐格写入）。

    columns: [(row_key, formatter_or_None), ...]，与表头列序一一对应。
    numeric: 数值列下标集合（按 UserRole 排序 + 右对齐）。
    chips:   {列下标: callable(row) -> (text, kind) | None}，该列渲染状态胶囊。
    payload: callable(row) -> object，结果存进第 0 列 UserRole，供 `cell_payload()`
             取回（服务名 / 备份路径）。
    align:   {列下标: _LEFT/_CENTER/_RIGHT}。
    """
    rows = list(rows or [])
    table.setSortingEnabled(False)
    table.setRowCount(0)      # 归零：确保上一轮 setCellWidget 的胶囊被真正析构
    table.setRowCount(len(rows))
    chips = chips or {}
    align = align or {}
    for r, row in enumerate(rows):
        for c, spec in enumerate(columns):
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
        if payload is not None:
            head = table.item(r, 0)
            if head is not None:
                head.setData(QtCore.Qt.UserRole, payload(row))
    table.setSortingEnabled(True)


def cell_payload(table, row, col=0):
    """取回 fill_table(payload=...) 存入第 col 列 UserRole 的对象。"""
    item = table.item(row, col)
    return None if item is None else item.data(QtCore.Qt.UserRole)


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


class BackupList(QtWidgets.QWidget):
    """「本机备份」表格区块：时间 / 配置节 / 大小 + 恢复到编辑区 + 删除。

    只是一层薄壳：数据来自 `backup.list_backups()`（纯本地读，不连路由器）；
    删除走二次确认；**恢复只把内容返回给调用方**，绝不直接写路由器。
    `backup` 模块由 `bind()` 注入，避免本文件顶层反向 import 纯逻辑层。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._module = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sizing()["radius_xs"])
        head = QtWidgets.QHBoxLayout()
        self.title = make_label("", role="caption", parent=self)
        head.addWidget(self.title)
        head.addStretch(1)
        for text, attr, slot, kind in (("恢复到编辑区", "btn_restore",
                                        self.on_restore, "default"),
                                       ("删除备份", "btn_delete",
                                        self.on_delete, "danger")):
            btn = make_button(text, kind=kind, size="sm", parent=self)
            btn.clicked.connect(slot)
            head.addWidget(btn)
            setattr(self, attr, btn)
        lay.addLayout(head)
        self.table = make_table(("备份时间", "配置节", "大小"), parent=self,
                                min_height=sizing()["log_table_min_height"])
        lay.addWidget(self.table)

    def bind(self, backup_module):
        """注入 `backup` 模块并立即刷新列表。"""
        self._module = backup_module
        self.refresh()

    def refresh(self):
        if self._module is None:
            return
        items = self._module.list_backups()
        self.title.setText(f"本机备份（最多 {self._module.MAX_BACKUPS} 份，"
                           f"当前 {len(items)} 份）")
        fill_table(self.table,
                   [{"ts": b.get("ts"), "section": b.get("section"),
                     "size": self._module.format_size(b.get("size")),
                     "path": b.get("path"), "name": b.get("name")}
                    for b in items],
                   (("ts", None), ("section", None), ("size", None)),
                   payload=lambda r: r["path"])

    def selected(self):
        """当前选中的备份条目；未选中返回 None。"""
        row = self.table.currentRow()
        return cell_payload(self.table, row) if row >= 0 else None

    def on_restore(self):
        """把选中备份的文本返回给调用方（灌进编辑区）；失败返回 None。"""
        item = self.selected()
        if not item:
            notify(self, "未选择", "请先在备份列表里选中一行。", error=True)
            return None
        content = self._module.read_backup(item.get("path"))
        if content is None:
            alert(self, "恢复失败", "读取该备份失败，或路径不在备份目录内。")
        return content

    def on_delete(self):
        item = self.selected()
        if not item:
            notify(self, "未选择", "请先在备份列表里选中一行。", error=True)
            return
        if not confirm(self, "确认删除备份",
                       f"即将删除本机备份 {item.get('name')}"
                       f"（{self._module.format_size(item.get('size'))}）。\n\n"
                       f"删除后无法再用它回滚路由器上该节的配置。\n\n确认删除？",
                       ok_text="删除"):
            return
        if self._module.delete_backup(item.get("path")):
            self.refresh()
            notify(self, "已删除", f"备份 {item.get('name')} 已删除。")
        else:
            alert(self, "删除失败", "文件可能已被占用，或路径不在备份目录内。")
