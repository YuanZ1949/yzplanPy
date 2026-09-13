"""ui/log_viewer.py: 独立的日志查看对话框，可从设置页或标题栏按钮打开。"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel, ComboBox, PushButton, StrongBodyLabel

_, QtCore, QtGui, QtWidgets = import_qt()


class LogViewerDialog(QtWidgets.QDialog):
    """独立日志查看窗口，带级别/来源筛选、搜索、自动刷新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        p = theme_palette()
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

        btn_refresh = PushButton("刷新")
        btn_refresh.clicked.connect(self._refresh_logs)
        toolbar.addWidget(btn_refresh)

        btn_top = PushButton("回到顶部")
        btn_top.clicked.connect(self._scroll_to_top)
        toolbar.addWidget(btn_top)

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
        make_adaptive_table(self.log_table, min_widths={3: 200})
        self.log_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setStyleSheet(
            f"QTableWidget {{ border: none; background: transparent; gridline-color: {p['table_gridline']}; }}"
            f"QTableWidget::item:selected {{ background: {p['table_sel_bg']}; }}"
            "QTableWidget::item:hover { background: transparent; }"
            f"QTableWidget::item:selected:hover {{ background: {p['table_sel_bg']}; }}"
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
        self._log_timer.timeout.connect(lambda: self._refresh_logs(preserve_scroll=True))
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
        from ui.adaptive_table import calc_cell_content_width
        avail_width = calc_cell_content_width(self.log_table.columnWidth(3), min_width=200)
        rect = fm.boundingRect(0, 0, avail_width, 20000, QtCore.Qt.TextWordWrap, text)
        self.log_table.setRowHeight(row, max(24, rect.height() + 10))

    def _load_log_sources(self):
        from core.logger import get_loggers, LOG_DIR
        import os, re
        sources = get_loggers()
        self.combo_log_source.blockSignals(True)
        current = self.combo_log_source.currentData()
        self.combo_log_source.clear()

        # 第一组：内存日志（按 logger 名筛选）
        self.combo_log_source.addItem("全部来源（内存日志）", userData="memory")
        for s in sources:
            self.combo_log_source.addItem(s, userData=f"memory:{s}")
        self.combo_log_source.addItem("─────────────────", userData="__separator__")

        # 第二组：文件日志（data/logs/ 下所有文件）
        log_dir = LOG_DIR
        if os.path.isdir(log_dir):
            for f in sorted(os.listdir(log_dir), reverse=True):
                if not f.endswith(".log") and not f.endswith(".log.1") and not f.endswith(".log.2"):
                    continue
                path = os.path.join(log_dir, f)
                if not os.path.isfile(path):
                    continue
                size = os.path.getsize(path)
                size_str = f"{size // 1024}KB" if size < 1024 * 1024 else f"{size / (1024*1024):.1f}MB"
                self.combo_log_source.addItem(f"📄 {f} ({size_str})", userData=path)

        if current and current != "__separator__":
            idx = self.combo_log_source.findData(current)
            if idx >= 0:
                self.combo_log_source.setCurrentIndex(idx)
        self.combo_log_source.blockSignals(False)

    def _refresh_logs(self, preserve_scroll=False):
        from core.logger import get_memory_logs, read_log_file
        import re
        level = self.combo_log_level.currentData()
        source = self.combo_log_source.currentData()
        keyword = self.search_input.text().strip() or None

        # 记录刷新前的滚动状态：内容以「最新在上」排列，刷新会向顶部追加新行。
        # 若需保留当前阅读位置，就用新增行的高度(+新最大值-旧最大值)补偿，避免窗口跳回顶部。
        sb = self.log_table.verticalScrollBar()
        prev_scroll = sb.value()
        prev_max = sb.maximum()

        # ---- 判断是内存日志还是文件日志 ----
        if source is None or (isinstance(source, str) and source.startswith("memory")):
            # 内存日志（原逻辑）
            logger_name = source.split(":", 1)[1] if source and ":" in source else None
            logs = get_memory_logs(level=level, logger_name=logger_name, keyword=keyword, limit=1000)
        else:
            # 文件日志
            logs = self._read_file_logs(source, level, keyword)

        self.log_table.setRowCount(len(logs))
        p = theme_palette()
        level_colors = {
            "DEBUG": "#888",
            "INFO": p["log_info"],
            "WARNING": p["log_warning"],
            "ERROR": p["log_error"],
            "CRITICAL": p["log_critical"],
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
            source_item.setForeground(QtGui.QColor(p["log_source"]))
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

        if not logs:
            return

        if preserve_scroll:
            # 新行向顶部追加：把滚动位置下移新增内容的高度，保持用户正在看的那批日志不动。
            added_height = sb.maximum() - prev_max
            target = prev_scroll + added_height
            sb.setValue(target)
        else:
            # 手动筛选/搜索/展开等操作时，回到顶部（最新）。
            sb.setValue(0)

    def _read_file_logs(self, path, level_filter, keyword):
        """读取文件日志并解析为统一格式。"""
        import re, os
        from core.logger import read_log_file
        lines = read_log_file(path, tail_lines=3000)  # 限制读取行数，避免内存爆
        if not lines:
            return []

        # 判断是否为 yzplan.log 标准格式
        is_yzplan_log = re.search(r'yzplan\.log', path) is not None

        logs = []
        for line in lines:
            line = line.rstrip("\n\r")
            if not line:
                continue

            if is_yzplan_log:
                # 解析：YYYY-MM-DD HH:MM:SS [LEVEL    ] logger: message
                m = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\[([A-Z ]+)\]\s*(\S+?):\s*(.*)', line)
                if m:
                    time_str, level, logger, message = m.groups()
                    level = level.strip()
                    logs.append({"time": time_str, "level": level, "logger": logger, "message": message})
                    continue
                # 解析失败，作为原始行
                logs.append({"time": "", "level": "RAW", "logger": os.path.basename(path), "message": line})
            else:
                # 非标准格式：原始行显示
                # 尝试提取时间戳（如果有）
                m = re.match(r'^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2})', line)
                time_str = m.group(1) if m else ""
                # 判断级别（ERROR/WARNING/DEBUG/INFO）
                level = "INFO"
                for lv in ["CRITICAL", "ERROR", "WARNING", "DEBUG", "INFO"]:
                    if lv in line.upper():
                        level = lv
                        break
                logs.append({"time": time_str, "level": level, "logger": os.path.basename(path), "message": line})

        # 过滤级别
        if level_filter:
            logs = [r for r in logs if r["level"] == level_filter]

        # 过滤关键词
        if keyword:
            kw = keyword.lower()
            logs = [r for r in logs if kw in r["message"].lower() or kw in r["logger"].lower()]

        # 最新的在前（按时间降序排列，假设文件内容是时间顺序）
        logs.reverse()
        return logs[:2000]  # 最多返回2000条

    def _scroll_to_top(self):
        self.log_table.verticalScrollBar().setValue(0)

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
