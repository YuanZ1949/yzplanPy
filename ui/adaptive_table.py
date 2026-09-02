"""ui/adaptive_table.py: 让 QTableWidget 列宽自适应窗口的共享工具。

行为：
- 所有列都设为 Interactive（可手动拖拽调整列宽）。
- 记录用户调整后的列宽为「基准列宽」。
- 窗口/表格宽度变化时，对所有列宽按百分比等比缩放（不破坏用户的相对比例）。
- 右边界始终贴合窗口（缩放后微调最后一列吸收取整误差）。
- 首次显示时按表头/内容做一次性自适应初值，然后冻结为基准。
"""

from core.qt_bootstrap import import_qt

_, QtCore, _, QtWidgets = import_qt()


class _AdaptiveFilter(QtCore.QObject):
    default_header_delta = 40  # 表头文本左右留白

    def __init__(self, table_widget, min_column_width=40):
        super().__init__(table_widget)
        self.table = table_widget
        self.min_column_width = min_column_width
        self._header = table_widget.horizontalHeader()
        self._base_widths = None       # 用户调整后的基准列宽（按列序）
        self._resizing = False         # 程序化 resize 中，避免被 sectionResized 反向记录
        self._ready = False
        self._pending = False          # 已排队待执行的延迟 reflow

        # 允许表格随窗口收缩（否则 Interactive 内容宽度会成为最小宽度，
        # 在特定宽度处无法继续等比缩放，出现“列宽突然还原/卡住”）
        table_widget.setMinimumWidth(0)
        table_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                   QtWidgets.QSizePolicy.Expanding)
        self._header.setMinimumSectionSize(20)
        self._header.setDefaultSectionSize(80)

        self._set_all_interactive()
        # sectionResized: 用户拖拽（或任何外部改动）记录为新基准
        self._header.sectionResized.connect(self._on_section_resized)
        table_widget.installEventFilter(self)
        QtCore.QTimer.singleShot(0, self._first_measure)

    def _set_all_interactive(self):
        for c in range(self.table.columnCount()):
            self._header.setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)

    # ── 首次测量：按表头/内容自适应初值 ──────────────────────────────
    def _first_measure(self):
        if self._ready:
            return
        if self.table.width() <= 0 or self.table.columnCount() == 0:
            QtCore.QTimer.singleShot(0, self._first_measure)
            return
        widths = []
        for c in range(self.table.columnCount()):
            w = self._content_width(c)
            widths.append(max(self.min_column_width, w))
        self._base_widths = list(widths)
        self._ready = True
        self._reflow()

    def _content_width(self, col):
        fm = self._header.fontMetrics()
        header_text = self._header.model().headerData(col, QtCore.Qt.Horizontal) or ""
        cw = fm.horizontalAdvance(header_text) + self.default_header_delta
        limit = min(50, self.table.rowCount())
        for r in range(limit):
            item = self.table.item(r, col)
            if item is not None:
                cw = max(cw, fm.horizontalAdvance(item.text()) + 24)
        return cw

    # ── 记录基准列宽（用户调整后）────────────────────────────────────
    def _on_section_resized(self, logical_idx, old_size, new_size):
        # 程序化缩放期间忽略，避免把缩放结果反向记为基准
        if self._resizing:
            return
        if self._base_widths is None or logical_idx >= len(self._base_widths):
            return
        self._base_widths[logical_idx] = new_size

    # ── 百分比等比缩放 + 右边界贴合 ─────────────────────────────────
    def _reflow(self):
        if not self._ready or self._base_widths is None:
            return
        viewport_w = self.table.viewport().width()
        if viewport_w <= 0:
            return
        total = sum(self._base_widths)
        if total <= 0:
            return
        # 按基准列宽等比缩放到目标宽度
        factor = viewport_w / total
        widths = [int(w * factor) for w in self._base_widths]
        # 若过窄导致超出，改按比例压缩（允许低于 min_column_width，避免横向滚动条带来的“突然还原”）
        if sum(widths) > viewport_w:
            widths = [max(0, int(w * factor)) for w in self._base_widths]
        # 最后一列吸收取整误差，保证右边界贴合窗口
        widths[-1] = viewport_w - sum(widths[:-1])
        if widths[-1] < 0:
            widths[-1] = 0
        self._resizing = True
        try:
            for c, w in enumerate(widths):
                self._header.resizeSection(c, w)
        finally:
            self._resizing = False

    # ── 事件处理 ─────────────────────────────────────────────────────
    def _schedule_reflow(self):
        # 表格 Resize 事件触发时 viewport 宽度仍为旧值，需延迟到布局落定后再计算
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._do_deferred_reflow)

    def _do_deferred_reflow(self):
        self._pending = False
        self._reflow()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Resize and obj is self.table:
            self._schedule_reflow()
        return False


def make_adaptive_table(table_widget, min_column_width=40):
    """让指定 QTableWidget 的列宽自适应窗口。返回过滤器对象（需持有以防被回收）。"""
    return _AdaptiveFilter(table_widget, min_column_width=min_column_width)
