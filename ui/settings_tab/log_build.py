"""SettingsTab 运行日志区构建：级别/来源筛选、搜索、导出、上下文菜单。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, ComboBox, PushButton, StrongBodyLabel
_, QtCore, QtGui, QtWidgets = import_qt()
from .mcp import SettingsTab

class SettingsTab(SettingsTab):  # type: ignore[reportGeneralTypeIssues]

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
