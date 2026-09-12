"""RSS 页面：工具栏构建。"""

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()
from .page_grips import _RssPageWidget
from .styles import _btn_style
from .text_utils import _qf


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]
    def _build_tool_bar(self, rss_c, root):
        """单行工具条：筛选 / 搜索 / 视图开关 / 批量。"""
        qf = _qf()

        tool_bar = QtWidgets.QFrame()
        tool_bar.setObjectName("rssToolBar")
        tool_bar.setStyleSheet(
            ("QFrame#rssToolBar {{ background: {ctrl_bg}; border: 1px solid {ctrl_border}; "
             "border-radius: 8px; }}").format(**rss_c))
        self.tool_bar = tool_bar
        tool_row = QtWidgets.QHBoxLayout(tool_bar)
        tool_row.setContentsMargins(6, 4, 6, 4)
        tool_row.setSpacing(6)

        self._date_preset_labels = {"today": "今天", "week": "本周", "month": "本月"}
        self.btn_date_filter = qf["DropDownPushButton"]("时间筛选")
        self.btn_date_filter.setStyleSheet(_btn_style(min_width=0, padding="6px 14px", radius=8))
        self.btn_date_filter.setToolTip("按发布时间筛选（快捷区间或自定义日期范围）")
        self._date_menu = qf["RoundMenu"](parent=self)
        self._date_quick_actions = {}
        _date_group = QtGui.QActionGroup(self._date_menu)
        for _key, _label in self._date_preset_labels.items():
            act = QtGui.QAction(_label, self._date_menu)
            self._date_menu.addAction(act)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked, k=_key: self._set_date_preset(k))
            _date_group.addAction(act)
            self._date_quick_actions[_key] = act
        act_clear_date = QtGui.QAction("清除时间筛选", self._date_menu)
        self._date_menu.addAction(act_clear_date)
        act_clear_date.triggered.connect(lambda: self._set_date_preset(None))
        self._date_menu.addSeparator()
        _date_wg = QtWidgets.QWidget()
        _date_row = QtWidgets.QHBoxLayout(_date_wg)
        _date_row.setContentsMargins(14, 6, 14, 8)
        _date_row.setSpacing(6)
        _date_row.addWidget(QtWidgets.QLabel("从"))
        self.date_from = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        _date_row.addWidget(self.date_from)
        _date_row.addWidget(QtWidgets.QLabel("到"))
        self.date_to = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        _date_row.addWidget(self.date_to)
        _btn_range_apply = QtWidgets.QPushButton("应用")
        _btn_range_apply.clicked.connect(self._apply_date_range)
        _date_row.addWidget(_btn_range_apply)
        _btn_range_clear = QtWidgets.QPushButton("清除")
        _btn_range_clear.clicked.connect(lambda: self._set_date_preset(None))
        _date_row.addWidget(_btn_range_clear)
        _act_range = QtWidgets.QWidgetAction(self._date_menu)
        _act_range.setDefaultWidget(_date_wg)
        self._date_menu.addAction(_act_range)
        self.btn_date_filter.setMenu(self._date_menu)
        # btn_date_filter 在搜索组之后统一加入 tool_row

        # combo_tag 隐藏保留：由「筛选▾」菜单驱动，_load_items 仍读取 currentData()
        self.combo_tag = qf["ComboBox"]()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        self.combo_tag.setMinimumWidth(120)
        self.combo_tag.currentIndexChanged.connect(self._load_items)

        self.combo_search_field = qf["ComboBox"]()
        self.combo_search_field.addItems(["全部", "标题", "描述", "链接"])
        self.combo_search_field.setFixedWidth(64)
        self.combo_search_field.currentIndexChanged.connect(self._load_items)

        self.search_input = qf["SearchLineEdit"]()
        self.search_input.setPlaceholderText("搜索标题 / 描述 / 链接…")
        self.search_input.setMinimumWidth(180)
        self.search_input.returnPressed.connect(self._load_items)
        self.search_input.searchSignal.connect(self._load_items)
        self.search_input.clearSignal.connect(self._load_items)

        self._current_date_range = None

        # ── 隐藏控件：加入 tool_row 但不可见（状态由顶部「筛选▾/阅读▾/批量▾」菜单驱动）──
        self.btn_favorites = qf["ToggleButton"]("仅收藏")
        self.btn_favorites.setCheckable(True)
        self.btn_favorites.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_favorites)
        self.btn_favorites.setVisible(False)

        self.btn_unread = qf["ToggleButton"]("仅未读")
        self.btn_unread.setCheckable(True)
        self.btn_unread.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_unread)
        self.btn_unread.setVisible(False)

        self.chk_select_all = qf["CheckBox"]("全选")
        self.chk_select_all.stateChanged.connect(self._select_all)
        tool_row.addWidget(self.chk_select_all)
        self.chk_select_all.setVisible(False)

        # ── 标题 + 搜索组（字段下拉 + 输入框紧贴）──────
        _title_wg = QtWidgets.QWidget()
        _title_row = QtWidgets.QHBoxLayout(_title_wg)
        _title_row.setContentsMargins(0, 0, 0, 0)
        _title_row.setSpacing(6)
        _globe = QtWidgets.QLabel("◎")
        _globe.setFixedSize(26, 26)
        _globe.setAlignment(QtCore.Qt.AlignCenter)
        _globe.setStyleSheet(
            f"background: {rss_c['accent_bg']}; color: {rss_c['accent']}; "
            f"border: 1px solid {rss_c['accent']}; border-radius: 8px; font-size: 14px;")
        self._globe = _globe
        _lbl_title = qf["StrongBodyLabel"]("RSS 聚合")
        _lbl_title.setStyleSheet(
            f"color: {rss_c['text_primary']}; font-size: 16px; font-weight: 700;")
        self._lbl_title = _lbl_title
        _title_row.addWidget(_globe)
        _title_row.addWidget(_lbl_title)
        tool_row.addWidget(_title_wg)

        _search_wg = QtWidgets.QFrame()
        _search_wg.setObjectName("rssSearchBox")
        _search_wg.setStyleSheet(
            f"QFrame#rssSearchBox {{ background: {rss_c['ctrl_bg']}; "
            f"border: 1px solid {rss_c['ctrl_border']}; border-radius: 9px; }}")
        _search_row = QtWidgets.QHBoxLayout(_search_wg)
        _search_row.setContentsMargins(2, 1, 2, 1)
        _search_row.setSpacing(0)
        _search_row.addWidget(self.combo_search_field)
        _search_row.addWidget(self.search_input)
        self._search_wg = _search_wg
        tool_row.addWidget(_search_wg)

        tool_row.addWidget(self.btn_date_filter)

        # ── 筛选▾：阅读状态 + 类型 + 标签 ────────────
        self.btn_filter = qf["DropDownPushButton"]("筛选")
        self.btn_filter.setStyleSheet(_btn_style(min_width=0, padding="6px 14px", radius=8))
        self._filter_menu = qf["RoundMenu"](parent=self)

        def _mk_check_action(text, btn):
            act = QtGui.QAction(text, self._filter_menu)
            act.setCheckable(True)
            act.setChecked(btn.isChecked())
            act.triggered.connect(lambda checked, b=btn: b.setChecked(checked))
            return act

        def _sync_filter_checks():
            for act, btn in ((self.act_fav_only, self.btn_favorites),
                             (self.act_unread_only, self.btn_unread)):
                act.blockSignals(True)
                act.setChecked(btn.isChecked())
                act.blockSignals(False)

        self.act_fav_only = _mk_check_action("仅收藏", self.btn_favorites)
        self._filter_menu.addAction(self.act_fav_only)
        self.act_unread_only = _mk_check_action("仅未读", self.btn_unread)
        self._filter_menu.addAction(self.act_unread_only)
        self.btn_favorites.toggled.connect(_sync_filter_checks)
        self.btn_unread.toggled.connect(_sync_filter_checks)

        self._filter_menu.addSeparator()
        self._type_menu = qf["RoundMenu"]("类型", parent=self._filter_menu)
        self._filter_menu.addMenu(self._type_menu)
        self._type_actions = []
        _type_group = QtGui.QActionGroup(self._type_menu)
        for _t_label, _t_data in (("全部类型", None), ("磁链", "__磁链__"), ("文章", "__文章__")):
            _act = QtGui.QAction(_t_label, self._type_menu)
            _act.setCheckable(True)
            _act.triggered.connect(
                lambda _c=False, data=_t_data: self.combo_tag.setCurrentIndex(
                    max(0, next((i for i in range(self.combo_tag.count())
                                 if self.combo_tag.itemData(i) == data), -1))))
            _type_group.addAction(_act)
            self._type_menu.addAction(_act)
            self._type_actions.append(_act)
        self._type_actions[0].setChecked(True)

        self._filter_menu.addSeparator()
        self._tag_menu = qf["RoundMenu"]("标签", parent=self._filter_menu)
        self._filter_menu.addMenu(self._tag_menu)

        self.btn_filter.setMenu(self._filter_menu)
        tool_row.addWidget(self.btn_filter)

        # ── 阅读▾ ─────────────────────────────────
        self.btn_read_ops = qf["DropDownPushButton"]("阅读")
        self.btn_read_ops.setStyleSheet(_btn_style(min_width=0, padding="6px 14px", radius=8))
        self._read_menu = qf["RoundMenu"](parent=self)
        self._batch_actions = {}
        _act_read = QtGui.QAction("标记选中已读", self._read_menu)
        _act_read.triggered.connect(self._batch_mark_read)
        self._read_menu.addAction(_act_read)
        self._batch_actions["read"] = _act_read
        _act_unread = QtGui.QAction("标记选中未读", self._read_menu)
        _act_unread.triggered.connect(self._batch_mark_unread)
        self._read_menu.addAction(_act_unread)
        self._batch_actions["unread"] = _act_unread
        self._read_menu.addSeparator()
        _act_all_read = QtGui.QAction("标记全部已读", self._read_menu)
        _act_all_read.triggered.connect(self._mark_all_read)
        self._read_menu.addAction(_act_all_read)
        self.btn_read_ops.setMenu(self._read_menu)
        tool_row.addWidget(self.btn_read_ops)

        # ── 批量▾（Primary）────────────────────────
        self.btn_batch_ops = qf["PrimaryDropDownPushButton"]("批量")
        self.btn_batch_ops.setToolTip("对选中条目执行批量操作")
        self._batch_menu = qf["RoundMenu"](parent=self)
        _act_select_all = QtGui.QAction("全选", self._batch_menu)
        _act_select_all.triggered.connect(
            lambda: self._select_all(QtCore.Qt.CheckState.Checked.value))
        self._batch_menu.addAction(_act_select_all)
        _act_invert = QtGui.QAction("反选", self._batch_menu)
        _act_invert.triggered.connect(self._invert_selection)
        self._batch_menu.addAction(_act_invert)
        _act_clear = QtGui.QAction("清空选择", self._batch_menu)
        _act_clear.triggered.connect(self._clear_selection)
        self._batch_menu.addAction(_act_clear)
        self._batch_menu.addSeparator()
        _act_delete = QtGui.QAction("删除选中", self._batch_menu)
        _act_delete.triggered.connect(self._batch_delete)
        self._batch_menu.addAction(_act_delete)
        self._batch_actions["delete"] = _act_delete
        self.btn_batch_ops.setMenu(self._batch_menu)
        tool_row.addWidget(self.btn_batch_ops)

        # ── 缩略图开关（checkable）────────────────────
        self.btn_thumb = QtWidgets.QPushButton()
        self.btn_thumb.setCheckable(True)
        self.btn_thumb.setChecked(self._show_thumbnails)
        self.btn_thumb.setStyleSheet(_btn_style(min_width=0, padding="6px 14px", radius=8))
        self.btn_thumb.setToolTip("列表条目是否显示缩略图")
        self._update_thumbnail_btn_text()
        self.btn_thumb.toggled.connect(self._toggle_thumbnails)
        tool_row.addWidget(self.btn_thumb)

        tool_row.addStretch(1)

        self._update_batch_buttons()
        root.addWidget(tool_bar)