"""SettingsTab 日志刷新与行操作：表填充、展开/收缩、清空、导出、右键菜单。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel
_, QtCore, QtGui, QtWidgets = import_qt()
from .log_build import SettingsTab

class SettingsTab(SettingsTab):

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
            expanded = self._is_log_expanded(i)
            text = log["message"] if expanded else self._elide_log(log["message"])
            msg_item = QtWidgets.QTableWidgetItem(text)
            if expanded:
                msg_item.setFlags(msg_item.flags() | QtCore.Qt.ItemIsEditable)
            msg_item.setToolTip(log["message"] if not expanded else "")
            self.log_table.setItem(i, 3, msg_item)
            self._apply_log_row_height(i, expanded)

        self._raw_messages = raw
        self.lb_log_count.setText(f"共 {len(logs)} 条")

        if self.chk_auto_scroll.isChecked() and logs:
            self.log_table.scrollToBottom()

    @staticmethod
    def _elide_log(text):
        return text if len(text) <= 200 else text[:200] + "…"

    def _set_all_message_expand(self, expanded):
        self._all_expanded = expanded
        self._refresh_logs()

    def _is_log_expanded(self, row):
        return self._all_expanded or (row in self._expanded_rows)

    def _on_log_cell_double_clicked(self, row, col):
        if col == 3 and 0 <= row < self.log_table.rowCount():
            item = self.log_table.item(row, col)
            expand = not self._is_log_expanded(row)
            if expand:
                self._expanded_rows.add(row)
            else:
                self._expanded_rows.discard(row)
            if item and row in self._raw_messages:
                if expand:
                    item.setText(self._raw_messages[row])
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                else:
                    item.setText(self._elide_log(self._raw_messages[row]))
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self._apply_log_row_height(row, expand)

    def _apply_log_row_height(self, row, expand):
        if not 0 <= row < self.log_table.rowCount():
            return
        text = self._raw_messages.get(row, "")
        if not expand:
            self.log_table.setRowHeight(row, 24)
            return
        fm = QtGui.QFontMetrics(QtGui.QFont("Microsoft YaHei", 9))
        avail_width = max(200, self.log_table.columnWidth(3) - 8)
        rect = fm.boundingRect(0, 0, avail_width, 20000, QtCore.Qt.TextWordWrap, text)
        self.log_table.setRowHeight(row, max(24, rect.height() + 10))

    def _clear_logs(self):
        from core.logger import clear_memory_logs
        clear_memory_logs()
        self._refresh_logs()

    def _export_logs(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.widget, "导出日志", "yzplan_logs.txt", "文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            try:
                from core.logger import get_memory_logs
                logs = get_memory_logs(limit=10000)
                with open(path, "w", encoding="utf-8") as f:
                    for log in logs:
                        f.write(f"{log['time']} [{log['level']:<8}] {log['logger']}: {log['message']}\n")
                QtWidgets.QMessageBox.information(self.widget, "成功", f"已导出 {len(logs)} 条日志到 {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self.widget, "错误", f"导出失败: {e}")

    def _show_log_context_menu(self, pos):
        item = self.log_table.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self.widget)
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
