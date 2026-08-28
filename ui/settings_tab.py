"""程序设置选项卡：主题、壁纸、毛玻璃、开机自启、关闭行为、日志。"""
import os

from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, PushButton, StrongBodyLabel, SwitchButton

_, QtCore, QtGui, QtWidgets = import_qt()


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

        behavior_card = self._make_card(il, "行为")
        self.cb_autostart = self._make_switch_row(behavior_card, "开机自动启动", "登录时在后台启动")
        self.cb_close_tray = self._make_switch_row(behavior_card, "关闭窗口时最小化到系统托盘", "窗口关闭后程序驻留托盘")
        self.cb_start_hidden = self._make_switch_row(behavior_card, "启动时隐藏主界面（仅显示托盘）", "开机自启时不弹出主窗口")

        log_card = self._make_card(il, "运行日志")
        self._build_log_section(log_card)

        il.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
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
        combo.addItem("跟随系统", "auto")
        combo.addItem("浅色", "light")
        combo.addItem("深色", "dark")
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

    def _build_log_section(self, parent):
        toolbar = QtWidgets.QHBoxLayout()

        self.combo_log_level = ComboBox()
        self.combo_log_level.addItem("全部级别", None)
        self.combo_log_level.addItem("DEBUG", "DEBUG")
        self.combo_log_level.addItem("INFO", "INFO")
        self.combo_log_level.addItem("WARNING", "WARNING")
        self.combo_log_level.addItem("ERROR", "ERROR")
        self.combo_log_level.addItem("CRITICAL", "CRITICAL")
        self.combo_log_level.setMinimumWidth(100)
        self.combo_log_level.currentIndexChanged.connect(self._refresh_logs)
        toolbar.addWidget(StrongBodyLabel("级别:"))
        toolbar.addWidget(self.combo_log_level)

        self.combo_log_source = ComboBox()
        self.combo_log_source.addItem("全部来源", None)
        toolbar.addWidget(StrongBodyLabel("来源:"))
        toolbar.addWidget(self.combo_log_source)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索日志...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._refresh_logs)
        toolbar.addWidget(self.search_input)

        toolbar.addStretch(1)

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
        self.log_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.log_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.log_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.log_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setMinimumHeight(200)
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
            self.combo_log_source.addItem(s, s)
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

            msg_item = QtWidgets.QTableWidgetItem(log["message"])
            self.log_table.setItem(i, 3, msg_item)

        self.lb_log_count.setText(f"共 {len(logs)} 条")

        if self.chk_auto_scroll.isChecked() and logs:
            self.log_table.scrollToBottom()

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
