"""RSS 页面：_RssPageWidget（构造与初始化）。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from core.perf import timed

from .sidebar_actions import _RssSidebar
from .styles import _btn_style, _sidebar_qss
from .text_utils import _qf, _rss_colors

class _RssPageWidget(QtWidgets.QWidget):
    frameless = True  # 打开时使用无边框自定义标题栏窗口

    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self._current_page = 0
        self._all_items = []
        self._last_clicked_row = -1
        self._selected_hashes = set()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        self._node_item_by_head = {}
        self._group_children = {}
        self._head_buttons = {}
        self._head_by_member = {}

        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)

        rss_c = _rss_colors()

        # ── UI 构建（从 paintEvent 移入 __init__）──────────────
        self._build_ui(rss_c)

    def _build_ui(self, rss_c):
        """构建页面全部控件（一次性调用，避免重复创建）。"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        qf = _qf()

        # ── 单行工具条：筛选 / 搜索 / 视图开关 / 批量 ─────────
        tool_bar = QtWidgets.QFrame()
        tool_bar.setObjectName("rssToolBar")
        tool_bar.setStyleSheet(
            ("QFrame#rssToolBar {{ background: {ctrl_bg}; border: 1px solid {ctrl_border}; "
             "border-radius: 8px; }}").format(**rss_c))
        tool_row = QtWidgets.QHBoxLayout(tool_bar)
        tool_row.setContentsMargins(10, 6, 10, 6)
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
        self.combo_search_field.setFixedWidth(86)
        self.combo_search_field.currentIndexChanged.connect(self._load_items)

        self.search_input = qf["SearchLineEdit"]()
        self.search_input.setPlaceholderText("搜索标题 / 描述 / 链接…")
        self.search_input.setMinimumWidth(300)
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
        _lbl_title = qf["StrongBodyLabel"]("RSS 聚合")
        _lbl_title.setStyleSheet(
            f"color: {rss_c['text_primary']}; font-size: 16px; font-weight: 700;")
        _title_row.addWidget(_globe)
        _title_row.addWidget(_lbl_title)
        tool_row.addWidget(_title_wg)
        tool_row.addSpacing(8)

        _search_wg = QtWidgets.QFrame()
        _search_wg.setObjectName("rssSearchBox")
        _search_wg.setStyleSheet(
            f"QFrame#rssSearchBox {{ background: {rss_c['ctrl_bg']}; "
            f"border: 1px solid {rss_c['ctrl_border']}; border-radius: 9px; }}")
        _search_row = QtWidgets.QHBoxLayout(_search_wg)
        _search_row.setContentsMargins(6, 2, 6, 2)
        _search_row.setSpacing(0)
        _search_row.addWidget(self.combo_search_field)
        _search_row.addWidget(self.search_input)
        tool_row.addWidget(_search_wg)

        tool_row.addSpacing(8)
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

        tool_row.addStretch(1)

        self._update_batch_buttons()
        root.addWidget(tool_bar)

        # ── 三栏主体：侧栏 | 拖拽 | 列表 | 拖拽 | 预览 ─────────
        # 创建三栏容器
        self._three_col = QtWidgets.QHBoxLayout()
        self._three_col.setContentsMargins(0, 8, 0, 0)
        self._three_col.setSpacing(0)

        # 侧栏
        self._sidebar = _RssSidebar(self.owner, self)
        self._sidebar.setStyleSheet(_sidebar_qss())
        self.lb_status = self._sidebar.lb_status
        self.lb_summary = self._sidebar.lb_summary

        # 侧栏列
        _side_col = QtWidgets.QFrame()
        _side_col.setObjectName("rssSideCol")
        _side_col.setStyleSheet(
            f"QFrame#rssSideCol {{ background: {rss_c['panel']}; border: 1px solid {rss_c['border']}; "
            f"border-radius: 12px; padding: 12px; }}")
        _side_layout = QtWidgets.QVBoxLayout(_side_col)
        _side_layout.setContentsMargins(0, 0, 0, 0)
        _side_layout.setSpacing(0)
        _side_layout.addWidget(self._sidebar)
        self._three_col.addWidget(_side_col, 0)

        # 拖拽手柄1
        _grip1 = self._make_grip()
        self._three_col.addWidget(_grip1)

        # 列表面板
        _list_col = QtWidgets.QFrame()
        _list_col.setObjectName("rssListCol")
        _list_col.setStyleSheet(
            f"QFrame#rssListCol {{ background: {rss_c['panel']}; border: 1px solid {rss_c['border']}; "
            f"border-radius: 12px; padding: 12px; }}")
        _list_layout = QtWidgets.QVBoxLayout(_list_col)
        _list_layout.setContentsMargins(0, 0, 0, 0)
        _list_layout.setSpacing(0)

        self.item_list = QtWidgets.QListWidget()
        self.item_list.setObjectName("rssItemList")
        self.item_list.setAlternatingRowColors(False)
        self.item_list.viewport().setAutoFillBackground(False)
        self.item_list.setStyleSheet(
            ("QListWidget {{ background: transparent; border: none; }}"
             "QListWidget::item {{ margin: 1px 4px; padding: 4px 6px; border-radius: 6px; "
             "border: 1px solid transparent; }}"
             "QListWidget::item:hover {{ background: {row_hover}; "
             "border: 1px solid {border_strong}; }}"
             "QListWidget::item:selected {{ background: {row_selected}; "
             "border: 1px solid {accent}; }}").format(**rss_c)
        )
        self.item_list.itemDoubleClicked.connect(self._open_item)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.itemChanged.connect(self._on_item_changed)
        self.item_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.item_list.customContextMenuRequested.connect(self._show_context_menu)
        _list_layout.addWidget(self.item_list, 1)

        # 分页（列表列底部固定）
        page_row = QtWidgets.QHBoxLayout()
        page_row.setSpacing(6)
        page_row.addStretch(1)
        _pg_c = _rss_colors()
        self.btn_prev = QtWidgets.QPushButton("上一页")
        self.btn_prev.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        self.btn_prev.clicked.connect(self._prev_page)
        page_row.addWidget(self.btn_prev)

        self.lb_page = QtWidgets.QLabel("第 1 页")
        self.lb_page.setAlignment(QtCore.Qt.AlignCenter)
        self.lb_page.setStyleSheet(f"color: {_pg_c['text_secondary']}; padding: 0 4px;")
        page_row.addWidget(self.lb_page)

        self.btn_next = QtWidgets.QPushButton("下一页")
        self.btn_next.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        self.btn_next.clicked.connect(self._next_page)
        page_row.addWidget(self.btn_next)

        self.lb_total = QtWidgets.QLabel("")
        self.lb_total.setStyleSheet(f"color: {_pg_c['text_secondary']}; padding-right: 6px;")
        page_row.addWidget(self.lb_total)

        _page_wg = QtWidgets.QWidget()
        _page_wg.setLayout(page_row)
        _list_layout.addWidget(_page_wg)

        self._three_col.addWidget(_list_col, 1)

        # 拖拽手柄2
        _grip2 = self._make_grip()
        self._three_col.addWidget(_grip2)

        # 预览列
        _preview_col = QtWidgets.QFrame()
        _preview_col.setObjectName("rssPreviewCol")
        _preview_col.setStyleSheet(
            f"QFrame#rssPreviewCol {{ background: {rss_c['panel']}; border: 1px solid {rss_c['border']}; "
            f"border-radius: 12px; padding: 12px; }}")
        _preview_layout = QtWidgets.QVBoxLayout(_preview_col)
        _preview_layout.setContentsMargins(0, 0, 0, 0)
        _preview_layout.setSpacing(0)

        self._summary_title = QtWidgets.QLabel("点击左侧条目查看摘要…")
        self._summary_title.setWordWrap(True)
        self._summary_title.setStyleSheet(
            f"QLabel {{ font-size: 14px; font-weight: 700; background: transparent; color: {rss_c['text']}; }}"
        )

        self._summary_status = QtWidgets.QLabel("")
        self._summary_status.setFixedHeight(22)
        self._summary_status.setStyleSheet(
            "QLabel { font-size: 11px; padding: 3px 10px; border-radius: 14px; font-weight: 600; }"
        )

        self._summary_meta = QtWidgets.QLabel("")
        self._summary_meta.setWordWrap(True)
        self._summary_meta.setStyleSheet(
            f"QLabel {{ color: {rss_c['text_secondary']}; font-size: 12px; background: transparent; line-height: 1.6; }}"
        )

        self._summary_desc = QtWidgets.QLabel("")
        self._summary_desc.setWordWrap(True)
        self._summary_desc.setMaximumHeight(120)
        self._summary_desc.setStyleSheet(
            f"QLabel {{ font-size: 12.5px; background: transparent; color: {rss_c['text']}; line-height: 1.7; }}"
        )
        self._summary_desc.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        # 预览分隔线
        _sep_line = QtWidgets.QWidget()
        _sep_line.setFixedHeight(1)
        _sep_line.setStyleSheet(f"background: {rss_c['border']};")

        self._preview_container = QtWidgets.QWidget()
        preview_panel = QtWidgets.QVBoxLayout(self._preview_container)
        preview_panel.setContentsMargins(8, 4, 8, 4)
        preview_panel.setSpacing(6)
        preview_panel.addWidget(self._summary_status)
        preview_panel.addWidget(self._summary_title)
        preview_panel.addWidget(self._summary_meta)
        preview_panel.addWidget(self._summary_desc)
        preview_panel.addWidget(_sep_line)

        # WebEngine 初始化为惰性创建：首次展示预览时才构造，避免拖慢 RSS 页打开。
        self._preview_web_ok = False
        self._preview_text_view = None
        self._preview_browser_view = None
        self.preview_browser = None
        self._preview_placeholder = QtWidgets.QLabel(
            "点击左侧条目，即可在下方预览文章正文…\n（原文链接用系统浏览器打开）")
        self._preview_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._preview_placeholder.setWordWrap(True)
        self._preview_placeholder.setStyleSheet(
            f"color: {rss_c['text_faint']}; font-size: 13px; padding: 20px;")
        self._preview_stack = QtWidgets.QStackedWidget()
        self._preview_stack.setStyleSheet(
            ("QStackedWidget {{ background: transparent; border-radius: 8px; }}").format(**rss_c)
        )
        self._summary_panel = QtWidgets.QWidget()
        self._summary_panel.setAutoFillBackground(False)
        _sum_lay = QtWidgets.QVBoxLayout(self._summary_panel)
        _sum_lay.setContentsMargins(0, 0, 0, 0)
        _sum_lay.addWidget(self._preview_placeholder)
        self._preview_stack.addWidget(self._summary_panel)
        self._preview_stack.setCurrentWidget(self._summary_panel)
        # 预览加载去抖：条目点击/标题按钮/聚合头等多个入口常在同帧触发 3 次
        # 加载。若对同一 WebEngine 视图并发 load()，会把主线程卡死在合成器
        # 里（复现为 GUI 冻结），因此窗口期内只保留最后一次加载请求。
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self._preview_do_load)
        self._preview_pending = None
        self._preview_fallback = None
        preview_panel.addWidget(self._preview_stack, 1)

        _preview_layout.addWidget(self._preview_container)

        self._three_col.addWidget(_preview_col, 1)

        root.addLayout(self._three_col, 1)

        with timed("rss.open.sidebar_reload"):
            self._sidebar.reload(reselect=True)
        with timed("rss.open.favicon_check"):
            if self.owner.store.feeds_needing_favicon():
                self.owner.refresh_favicons()
        self.setTabOrder(self.search_input, self.item_list)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        with timed("rss.open.load_items"):
            self._load_items()

        self.destroyed.connect(self._cleanup_preview)

    def _make_grip(self):
        """创建拖拽手柄（仿 HTML v4 设计）"""
        c = _rss_colors()
        grip = QtWidgets.QFrame()
        grip.setFixedWidth(7)
        grip.setStyleSheet(f"""
            QFrame {{
                background: transparent;
            }}
            QFrame:hover {{
                background: {c['accent']};
            }}
        """)
        # 添加中间的竖线
        line = QtWidgets.QFrame(grip)
        line.setFixedSize(3, 36)
        line.setStyleSheet(f"background: {c['border']}; border-radius: 2px;")
        layout = QtWidgets.QVBoxLayout(grip)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addStretch(1)
        layout.addWidget(line, 0, QtCore.Qt.AlignCenter)
        layout.addStretch(1)
        return grip

    def paintEvent(self, event):
        """v4 径向渐变背景——深色蓝+紫+绿，浅色蓝。"""
        c = _rss_colors()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if c["dark"]:
            # 底色
            p.fillRect(self.rect(), QtGui.QColor("#1b1c1f"))
            # 径向渐变：中心蓝 → 紫 → 绿 → 透明
            grad = QtGui.QRadialGradient(w / 2, h / 2, max(w, h) * 0.55)
            grad.setColorAt(0.0, QtGui.QColor(74, 163, 255, 51))   # 0.20
            grad.setColorAt(0.4, QtGui.QColor(160, 107, 255, 26))  # 0.10
            grad.setColorAt(0.7, QtGui.QColor(37, 205, 150, 15))   # 0.06
            grad.setColorAt(1.0, QtCore.Qt.transparent)
        else:
            # 底色
            p.fillRect(self.rect(), QtGui.QColor("#e9ebf0"))
            # 径向渐变：上方蓝
            grad = QtGui.QRadialGradient(w / 2, h * 0.3, max(w, h) * 0.55)
            grad.setColorAt(0.0, QtGui.QColor(26, 115, 232, 38))   # 0.15
            grad.setColorAt(0.6, QtGui.QColor(26, 115, 232, 8))    # 0.03
            grad.setColorAt(1.0, QtCore.Qt.transparent)
        p.setBrush(grad)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRect(self.rect())
        p.end()
