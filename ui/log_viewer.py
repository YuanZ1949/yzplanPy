"""ui/log_viewer.py: 独立的日志查看对话框，可从设置页或标题栏按钮打开。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, ComboBox, PushButton, StrongBodyLabel

_, QtCore, QtGui, QtWidgets = import_qt()


class LogViewerDialog(QtWidgets.QDialog):
    """独立日志查看窗口，带级别/来源筛选、搜索、自动刷新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        self.setMinimumSize(800, 500)
        from core.ui_state import window_geometry
        window_geometry().apply(self, "log_viewer", default_size=(800, 500))
        self.finished.connect(lambda *_: window_geometry().capture(self, "log_viewer"))

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        toolbar = QtWidgets.QHBoxLayout()
        self.combo_log_level = ComboBox()
        self.combo_log_level.addItem("全部级别", userData=None)
        self.combo_log_level.addItem("DEBUG", userData="DEBUG")
        self.combo_log_level.addItem("INFO", userData="INFO")
        self.combo_log_level.addItem("WARNING", userData="WARNING")
        self.combo_log_level.addItem("ERROR", userData="ERROR")
        self.combo_log_level.addItem("CRITICAL", userData="CRITICAL")
        self.combo_log_level.setMinimumWidth(100)
        self.combo_log_level.currentIndexChanged.connect(self._refresh_logs)
        toolbar.addWidget(StrongBodyLabel("级别:"))
        toolbar.addWidget(self.combo_log_level)

        self.combo_log_source = ComboBox()
        self.combo_log_source.addItem("全部来源", userData=None)
        toolbar.addWidget(StrongBodyLabel("来源:"))
        toolbar.addWidget(self.combo_log_source)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索日志...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._refresh_logs)
        toolbar.addWidget(self.search_input)

        toolbar.addStretch(1)

        btn_expand = PushButton("展开消息")
        btn_expand.clicked.connect(lambda: self._set_all_message_expand(True))
        toolbar.addWidget(btn_expand)

        btn_collapse = PushButton("收缩消息")
        btn_collapse.clicked.connect(lambda: self._set_all_message_expand(False))
        toolbar.addWidget(btn_collapse)

        self.chk_auto_scroll = QtWidgets.QCheckBox("自动滚动")
        self.chk_auto_scroll.setChecked(True)
        toolbar.addWidget(self.chk_auto_scroll)

        btn_refresh = PushButton("刷新")
        btn_refresh.clicked.connect(self._refresh_logs)
        toolbar.addWidget(btn_refresh)

        btn_clear = PushButton("清空")
        btn_clear.clicked.connect(self._clear_logs)
        toolbar.addWidget(btn_clear)

        btn_export = PushButton("导出")
        btn_export.clicked.connect(self._export_logs)
        toolbar.addWidget(btn_export)

        lay.addLayout(toolbar)

        self.log_table = QtWidgets.QTableWidget()
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "级别", "来源", "消息"])
        from ui.adaptive_table import make_adaptive_table
        make_adaptive_table(self.log_table)
        self.log_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setStyleSheet(
            "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
            "QTableWidget::item:selected { background: rgba(128,128,128,0.12); }"
            "QTableWidget::item:hover { background: transparent; }"
            "QTableWidget::item:selected:hover { background: rgba(128,128,128,0.12); }"
        )
        self.log_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.log_table.customContextMenuRequested.connect(self._show_log_context_menu)
        lay.addWidget(self.log_table, 1)

        status_row = QtWidgets.QHBoxLayout()
        self.lb_log_count = BodyLabel("共 0 条")
        status_row.addWidget(self.lb_log_count)
        status_row.addStretch(1)
        lay.addLayout(status_row)

        self._log_timer = QtCore.QTimer(self)
        self._log_timer.timeout.connect(self._refresh_logs)
        self._log_timer.start(3000)

        self._all_expanded = False
        self._expanded_rows = set()
        self._raw_messages = {}
        self.log_table.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self._load_log_sources()
        self._refresh_logs()

    def _set_all_message_expand(self, expanded):
        self._all_expanded = expanded
        self._refresh_logs()

    def _on_cell_double_clicked(self, row, col):
        if col == 3 and 0 <= row < self.log_table.rowCount():
            item = self.log_table.item(row, col)
            expand = not self._is_expanded(row)
            self._set_row_expanded(row, item, expand)

    def _is_expanded(self, row):
        return self._all_expanded or (row in getattr(self, "_expanded_rows", set()))

    def _set_row_expanded(self, row, item, expand):
        rows = getattr(self, "_expanded_rows", None)
        if rows is None:
            rows = set()
            self._expanded_rows = rows
        if expand:
            rows.add(row)
        else:
            rows.discard(row)
        if item and row in self._raw_messages:
            msg = self._raw_messages[row]
            if expand:
                item.setText(msg)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            else:
                elided = self._elide(msg)
                item.setText(elided)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
        self._apply_row_height(row, expand)

    @staticmethod
    def _elide(text):
        return text if len(text) <= 200 else text[:200] + "…"

    def _apply_row_height(self, row, expand):
        if not 0 <= row < self.log_table.rowCount():
            return
        text = self._raw_messages.get(row, "")
        if not expand:
            self.log_table.setRowHeight(row, 24)
            return
        font = QtGui.QFont("Microsoft YaHei", 9)
        fm = QtGui.QFontMetrics(font)
        avail_width = max(200, self.log_table.columnWidth(3) - 8)
        rect = fm.boundingRect(0, 0, avail_width, 20000, QtCore.Qt.TextWordWrap, text)
        self.log_table.setRowHeight(row, max(24, rect.height() + 10))

    def _load_log_sources(self):
        from core.logger import get_loggers
        sources = get_loggers()
        self.combo_log_source.blockSignals(True)
        current = self.combo_log_source.currentData()
        self.combo_log_source.clear()
        self.combo_log_source.addItem("全部来源", None)
        for s in sources:
            self.combo_log_source.addItem(s, userData=s)
        if current:
            idx = self.combo_log_source.findData(current)
            if idx >= 0:
                self.combo_log_source.setCurrentIndex(idx)
        self.combo_log_source.blockSignals(False)

    def _refresh_logs(self):
        from core.logger import get_memory_logs
        level = self.combo_log_level.currentData()
        source = self.combo_log_source.currentData()
        keyword = self.search_input.text().strip() or None
        logs = get_memory_logs(level=level, logger_name=source, keyword=keyword, limit=1000)

        self.log_table.setRowCount(len(logs))
        level_colors = {
            "DEBUG": "#888",
            "INFO": "#1a73e8",
            "WARNING": "#f9a825",
            "ERROR": "#c5221f",
            "CRITICAL": "#7b1fa2",
        }

        raw = {}
        for i, log in enumerate(logs):
            time_item = QtWidgets.QTableWidgetItem(log["time"])
            time_item.setForeground(QtGui.QColor("#666"))
            self.log_table.setItem(i, 0, time_item)

            level_item = QtWidgets.QTableWidgetItem(log["level"])
            color = level_colors.get(log["level"], "#333")
            level_item.setForeground(QtGui.QColor(color))
            font = level_item.font()
            font.setBold(True)
            level_item.setFont(font)
            self.log_table.setItem(i, 1, level_item)

            source_item = QtWidgets.QTableWidgetItem(log["logger"])
            source_item.setForeground(QtGui.QColor("#1967d2"))
            self.log_table.setItem(i, 2, source_item)

            raw[i] = log["message"]
            expanded = self._is_expanded(i)
            text = log["message"] if expanded else self._elide(log["message"])
            msg_item = QtWidgets.QTableWidgetItem(text)
            if expanded:
                msg_item.setFlags(msg_item.flags() | QtCore.Qt.ItemIsEditable)
            msg_item.setToolTip(log["message"] if not expanded else "")
            self.log_table.setItem(i, 3, msg_item)
            self._apply_row_height(i, expanded)

        self._raw_messages = raw
        self.lb_log_count.setText(f"共 {len(logs)} 条")

        if self.chk_auto_scroll.isChecked() and logs:
            self.log_table.scrollToBottom()

    def _clear_logs(self):
        from core.logger import clear_memory_logs
        clear_memory_logs()
        self._refresh_logs()

    def _export_logs(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出日志", "yzplan_logs.txt", "文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            try:
                from core.logger import get_memory_logs
                logs = get_memory_logs(limit=10000)
                with open(path, "w", encoding="utf-8") as f:
                    for log in logs:
                        f.write(f"{log['time']} [{log['level']:<8}] {log['logger']}: {log['message']}\n")
                QtWidgets.QMessageBox.information(self, "成功", f"已导出 {len(logs)} 条日志到 {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _show_log_context_menu(self, pos):
        item = self.log_table.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)
        act_copy = menu.addAction("复制选中行")
        act_copy_all = menu.addAction("复制所有日志")
        menu.addSeparator()
        act_filter_level = menu.addAction("筛选此级别")
        act_filter_source = menu.addAction("筛选此来源")

        action = menu.exec_(self.log_table.mapToGlobal(pos))
        if not action:
            return

        if action == act_copy:
            rows = set(idx.row() for idx in self.log_table.selectedIndexes())
            lines = []
            for r in sorted(rows):
                line = " | ".join(
                    self.log_table.item(r, c).text()
                    for c in range(self.log_table.columnCount())
                    if self.log_table.item(r, c)
                )
                lines.append(line)
            QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        elif action == act_copy_all:
            lines = []
            for r in range(self.log_table.rowCount()):
                line = " | ".join(
                    self.log_table.item(r, c).text()
                    for c in range(self.log_table.columnCount())
                    if self.log_table.item(r, c)
                )
                lines.append(line)
            QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        elif action == act_filter_level:
            row = item.row()
            level_item = self.log_table.item(row, 1)
            if level_item:
                level = level_item.text()
                idx = self.combo_log_level.findData(level)
                if idx >= 0:
                    self.combo_log_level.setCurrentIndex(idx)
        elif action == act_filter_source:
            row = item.row()
            source_item = self.log_table.item(row, 2)
            if source_item:
                source = source_item.text()
                idx = self.combo_log_source.findData(source)
                if idx >= 0:
                    self.combo_log_source.setCurrentIndex(idx)
