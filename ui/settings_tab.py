"""程序设置选项卡：主题、壁纸、毛玻璃、开机自启、关闭行为、日志。"""
import os

from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, PushButton, StrongBodyLabel, SwitchButton

_, QtCore, QtGui, QtWidgets = import_qt()


class _MCPBridge(QtCore.QObject):
    """把后台线程的测试结果安全投递回主线程（QueuedConnection 自动按线程排队）。"""
    done = QtCore.Signal(bool, str)


class SettingsTab:
    def __init__(self, context):
        self.context = context
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("settings_tab")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(12, 12, 12, 12)

        header = StrongBodyLabel("程序设置")
        layout.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QtWidgets.QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(12)

        appearance_card = self._make_card(il, "外观")
        self.theme_combo = self._make_theme_row(appearance_card)
        self._make_wallpaper_row(appearance_card)
        self._make_acrylic_row(appearance_card)
        self._make_opacity_row(appearance_card)
        self._make_blur_radius_row(appearance_card)
        self._make_glass_opacity_row(appearance_card)

        behavior_card = self._make_card(il, "行为")
        self.cb_autostart = self._make_switch_row(behavior_card, "开机自动启动", "登录时在后台启动")
        self.cb_close_tray = self._make_switch_row(behavior_card, "关闭窗口时最小化到系统托盘", "窗口关闭后程序驻留托盘")
        self.cb_start_hidden = self._make_switch_row(behavior_card, "启动时隐藏主界面（仅显示托盘）", "开机自启时不弹出主窗口")

        mcp_card = self._make_card(il, "MCP 服务器")
        self._build_mcp_section(mcp_card)

        log_card = self._make_card(il, "运行日志")
        self._build_log_section(log_card)

        il.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self._mcp_bridge = _MCPBridge()
        self._mcp_bridge.done.connect(self._on_mcp_result, QtCore.Qt.QueuedConnection)
        self._load()

    def _make_card(self, parent, title):
        card = CardWidget()
        card.setObjectName(f"settings_card_{title}")
        card.setStyleSheet("background: transparent;")
        title_label = StrongBodyLabel(title)
        title_label.setStyleSheet("font-size: 13px; color: #888; background: transparent; margin-bottom: 2px;")
        parent.addWidget(title_label)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(16, 8, 16, 8)
        parent.addWidget(card)
        return lay

    def _make_theme_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("界面主题"))
        txt.addWidget(BodyLabel("统一调控界面深浅色，应用后立即生效"))
        rl.addLayout(txt, 1)
        combo = ComboBox()
        combo.addItem("跟随系统", userData="auto")
        combo.addItem("浅色", userData="light")
        combo.addItem("深色", userData="dark")
        rl.addWidget(combo)
        parent.addWidget(row)
        return combo

    def _make_wallpaper_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("主窗口壁纸"))
        txt.addWidget(BodyLabel("选择一张图片作为主窗口背景"))
        rl.addLayout(txt, 1)
        self.lb_wp_path = BodyLabel("")
        self.lb_wp_path.setStyleSheet("color: #999; max-width: 200px;")
        self.lb_wp_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        rl.addWidget(self.lb_wp_path)
        btn_browse = PushButton("浏览...")
        btn_browse.clicked.connect(self._browse_wallpaper)
        rl.addWidget(btn_browse)
        btn_clear = PushButton("清除")
        btn_clear.clicked.connect(self._clear_wallpaper)
        rl.addWidget(btn_clear)
        parent.addWidget(row)

    def _make_acrylic_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("毛玻璃效果"))
        txt.addWidget(BodyLabel("启用后壁纸会进行高斯模糊处理"))
        rl.addLayout(txt, 1)
        sw = SwitchButton()
        sw.setOnText("开")
        sw.setOffText("关")
        rl.addWidget(sw)
        parent.addWidget(row)
        self.sw_acrylic = sw

    def _make_opacity_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("壁纸透明度"))
        txt.addWidget(BodyLabel("数值越低壁纸越淡"))
        rl.addLayout(txt, 1)
        self.slider_opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setFixedWidth(160)
        self.lb_opacity_val = BodyLabel("35%")
        rl.addWidget(self.slider_opacity)
        rl.addWidget(self.lb_opacity_val)
        parent.addWidget(row)

    def _make_blur_radius_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("毛玻璃模糊程度"))
        txt.addWidget(BodyLabel("数值越高壁纸越朦胧，仅毛玻璃开启时生效"))
        rl.addLayout(txt, 1)
        self.slider_blur = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_blur.setRange(0, 40)
        self.slider_blur.setFixedWidth(160)
        self.lb_blur_val = BodyLabel("20px")
        rl.addWidget(self.slider_blur)
        rl.addWidget(self.lb_blur_val)
        parent.addWidget(row)

    def _make_glass_opacity_row(self, parent):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("毛玻璃透明度"))
        txt.addWidget(BodyLabel("数值越高毛玻璃越清晰，仅毛玻璃开启时生效"))
        rl.addLayout(txt, 1)
        self.slider_glass = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_glass.setRange(20, 100)
        self.slider_glass.setFixedWidth(160)
        self.lb_glass_val = BodyLabel("70%")
        rl.addWidget(self.slider_glass)
        rl.addWidget(self.lb_glass_val)
        parent.addWidget(row)

    def _make_switch_row(self, parent, title, caption):
        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 6, 0, 6)
        txt = QtWidgets.QVBoxLayout()
        t = StrongBodyLabel(title)
        txt.addWidget(t)
        cap = BodyLabel(caption)
        txt.addWidget(cap)
        rl.addLayout(txt, 1)
        sw = SwitchButton()
        sw.setOnText("开")
        sw.setOffText("关")
        rl.addWidget(sw)
        parent.addWidget(row)
        return sw

    def _build_mcp_section(self, parent):
        """MCP 服务器卡片：开关、启动命令、工具数量、测试连接。"""
        import json

        # 开关：是否在本应用内启动 Http MCP 服务（stdio 作为独立进程命令始终可用）
        mcp_sw_row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(mcp_sw_row)
        rl.setContentsMargins(0, 6, 0, 0)
        txt = QtWidgets.QVBoxLayout()
        txt.addWidget(StrongBodyLabel("启用 MCP HTTP 服务"))
        txt.addWidget(BodyLabel("在 127.0.0.1:8765 提供本地 MCP 接口，供外部客户端调用"))
        rl.addLayout(txt, 1)
        self.sw_mcp_http = SwitchButton()
        self.sw_mcp_http.setOnText("开")
        self.sw_mcp_http.setOffText("关")
        rl.addWidget(self.sw_mcp_http)
        parent.addWidget(mcp_sw_row)

        # 状态 / 工具数
        self.lb_mcp_status = BodyLabel("MCP 接口已注册，共 0 个工具")
        self.lb_mcp_status.setStyleSheet("color: #888;")
        parent.addWidget(self.lb_mcp_status)

        # stdio 与 http 启动命令
        def _cmd_row(label, command):
            row = QtWidgets.QWidget()
            rl2 = QtWidgets.QHBoxLayout(row)
            rl2.setContentsMargins(0, 2, 0, 2)
            rl2.addWidget(BodyLabel(label))
            edit = QtWidgets.QLineEdit(command)
            edit.setReadOnly(True)
            edit.setStyleSheet(
                "background: rgba(128,128,128,0.12); border: 1px solid rgba(128,128,128,0.2); "
                "border-radius: 5px; padding: 3px 6px; color: inherit;")
            edit.setCursorPosition(0)
            rl2.addWidget(edit, 1)
            btn = PushButton("复制")
            btn.clicked.connect(lambda _=False, e=edit: (
                QtWidgets.QApplication.clipboard().setText(e.text())))
            rl2.addWidget(btn)
            parent.addWidget(row)

        _cmd_row("stdio:", 'python mcp_server.py stdio')
        _cmd_row("HTTP:", 'python mcp_server.py http --port 8765')

        # 测试连接
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_test = PushButton("测试连接")
        btn_test.clicked.connect(self._test_mcp)
        btn_row.addWidget(btn_test)
        parent.addLayout(btn_row)

        # 初始化工具数量与开关状态
        try:
            import mcp_server
            self.lb_mcp_status.setText(f"MCP 接口已注册，共 {len(mcp_server.TOOLS)} 个工具")
        except Exception:
            self.lb_mcp_status.setText("MCP 模块未加载")
        enabled = self.context.config.get("mcp.enabled", False)
        self.sw_mcp_http.setChecked(bool(enabled))
        self.sw_mcp_http.checkedChanged.connect(self._on_mcp_http_toggled)

    def _on_mcp_http_toggled(self, on):
        """保存配置并在应用内启动/停止 MCP HTTP 服务线程。"""
        import threading
        self.context.config.set("mcp.enabled", bool(on))
        state = getattr(self, "_mcp_http_state", None)
        server = state.get("server") if state else None
        if on:
            if server is not None:
                return
            try:
                import mcp_server
                from wsgiref.simple_server import make_server
                host, port = "127.0.0.1", 8765
                httpd = make_server(host, port,
                                    lambda e, s: mcp_server._http_handler(e, s, {}))

                def serve():
                    httpd.serve_forever()

                t = threading.Thread(target=serve, daemon=True)
                t.start()
                self._mcp_http_state = {"alive": True, "server": httpd}
            except Exception:
                self._mcp_http_state = None
        else:
            if server is not None:
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            self._mcp_http_state = {"alive": False, "server": None}

    def _test_mcp(self):
        """后台线程只做轻量计算，结果经跨线程安全的 bridge 信号回到主线程再弹提示。

        禁止在后台线程直接创建/操作 Qt widget（Qt 非线程安全，会让主线程事件循环卡死）；
        也不能用 QTimer.singleShot（从非 GUI 线程调用时 0ms 定时器不会投递到主线程）。
        """
        import threading

        def _run():
            try:
                import mcp_server
                result = mcp_server.handle_message({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "todo_stats", "arguments": {}},
                })
                ok = result and result.get("result", {}).get("isError") is False
                msg = ("MCP 工作正常" if ok else "MCP 调用返回异常") + \
                      f": {len(mcp_server.TOOLS)} 个工具"
            except Exception as e:  # noqa: BLE001
                ok, msg = False, str(e)
            # 跨线程投递到主线程（QueuedConnection）；_on_mcp_result 只在主线程操作 GUI
            self._mcp_bridge.done.emit(ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _on_mcp_result(self, ok, msg):
        from qfluentwidgets import InfoBar, InfoBarPosition
        if ok:
            InfoBar.success("测试完成", msg, parent=self.widget,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
        else:
            InfoBar.error("MCP 测试失败", msg, parent=self.widget,
                          position=InfoBarPosition.TOP_RIGHT, duration=3000)

    def _build_log_section(self, parent):
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

        parent.addLayout(toolbar)

        self.log_table = QtWidgets.QTableWidget()
        self.log_table.setColumnCount(4)
        self.log_table.setHorizontalHeaderLabels(["时间", "级别", "来源", "消息"])
        from ui.adaptive_table import make_adaptive_table
        self._log_table_filter = make_adaptive_table(self.log_table)
        self.log_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setMinimumHeight(200)
        self.log_table.setStyleSheet(
            "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
            "QTableWidget::item:selected { background: rgba(128,128,128,0.12); }"
            "QTableWidget::item:hover { background: transparent; }"
            "QTableWidget::item:selected:hover { background: rgba(128,128,128,0.12); }"
        )
        self.log_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.log_table.customContextMenuRequested.connect(self._show_log_context_menu)
        parent.addWidget(self.log_table, 1)

        status_row = QtWidgets.QHBoxLayout()
        self.lb_log_count = BodyLabel("共 0 条")
        status_row.addWidget(self.lb_log_count)
        status_row.addStretch(1)
        parent.addLayout(status_row)

        self._log_timer = QtCore.QTimer()
        self._log_timer.timeout.connect(self._refresh_logs)
        self._log_timer.start(3000)

        self._all_expanded = False
        self._expanded_rows = set()
        self._raw_messages = {}
        self.log_table.cellDoubleClicked.connect(self._on_log_cell_double_clicked)

        self._load_log_sources()
        self._refresh_logs()

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

    def _load(self):
        import sys
        cfg = self.context.config

        if sys.platform == "win32":
            from core.autostart import autostart_enabled
            self.cb_autostart.setChecked(autostart_enabled())
            self.cb_autostart.checkedChanged.connect(self._on_autostart)
        else:
            self.cb_autostart.setEnabled(False)

        theme = cfg.get("ui.theme", "auto")
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        wp = cfg.get("ui.wallpaper", "")
        self.lb_wp_path.setText(os.path.basename(wp) if wp else "未设置")
        self.lb_wp_path.setToolTip(wp)

        self.sw_acrylic.setChecked(cfg.get("ui.acrylic", False))
        self.sw_acrylic.checkedChanged.connect(self._on_acrylic_changed)

        opacity = int(cfg.get("ui.wallpaper_opacity", 0.35) * 100)
        self.slider_opacity.setValue(opacity)
        self.lb_opacity_val.setText(f"{opacity}%")
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)

        blur = int(cfg.get("ui.acrylic_blur_radius", 35))
        self.slider_blur.setValue(blur)
        self.lb_blur_val.setText(f"{blur}px")
        self.slider_blur.valueChanged.connect(self._on_blur_changed)

        glass = int(cfg.get("ui.acrylic_opacity", 0.7) * 100)
        self.slider_glass.setValue(glass)
        self.lb_glass_val.setText(f"{glass}%")
        self.slider_glass.valueChanged.connect(self._on_glass_changed)

        self.cb_close_tray.setChecked(cfg.get("close_to_tray", True))
        self.cb_start_hidden.setChecked(cfg.get("window.start_hidden", False))
        self.cb_close_tray.checkedChanged.connect(self._on_close_tray_changed)
        self.cb_start_hidden.checkedChanged.connect(lambda b: cfg.set("window.start_hidden", b))

    def _on_theme_changed(self, index):
        mode = self.theme_combo.itemData(index)
        if not mode:
            return
        self.context.config.set("ui.theme", mode)
        from core.theme import apply_app_theme, apply_global_stylesheet, resolve_dark
        dark = apply_app_theme(mode)
        apply_global_stylesheet(self.context.config.get("ui.acrylic", False), dark=dark)

    def _browse_wallpaper(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget, "选择壁纸图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)",
        )
        if path:
            self.context.config.set("ui.wallpaper", path)
            self.lb_wp_path.setText(os.path.basename(path))
            self.lb_wp_path.setToolTip(path)
            self._apply_wallpaper()

    def _clear_wallpaper(self):
        self.context.config.set("ui.wallpaper", "")
        self.lb_wp_path.setText("未设置")
        self.lb_wp_path.setToolTip("")
        self._apply_wallpaper()

    def _on_acrylic_changed(self, on):
        self.context.config.set("ui.acrylic", on)
        from core.theme import apply_global_stylesheet
        apply_global_stylesheet(on)
        self._apply_wallpaper()

    def _on_opacity_changed(self, val):
        self.lb_opacity_val.setText(f"{val}%")
        self.context.config.set("ui.wallpaper_opacity", val / 100.0)
        self._apply_wallpaper()

    def _on_blur_changed(self, val):
        self.lb_blur_val.setText(f"{val}px")
        self.context.config.set("ui.acrylic_blur_radius", val)
        self._apply_wallpaper()

    def _on_glass_changed(self, val):
        self.lb_glass_val.setText(f"{val}%")
        self.context.config.set("ui.acrylic_opacity", val / 100.0)
        self._apply_wallpaper()

    def _apply_wallpaper(self):
        mw = getattr(self.context, "host_window", None)
        if mw and hasattr(mw, "apply_wallpaper"):
            mw.apply_wallpaper()

    def _on_autostart(self, enabled):
        from core.autostart import set_autostart
        set_autostart(enabled)

    def _on_close_tray_changed(self, on):
        self.context.config.set("close_to_tray", on)
        mw = getattr(self.context, "host_window", None)
        if mw:
            mw.close_to_tray = on
