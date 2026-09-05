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

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = _RssSidebar(owner, self)
        self._sidebar.setStyleSheet(_sidebar_qss())
        # 概览与状态 Label 位于侧边栏刷新/全部刷新上方，此处仅建立别名
        self.lb_status = self._sidebar.lb_status
        self.lb_summary = self._sidebar.lb_summary

        section_items = QtWidgets.QVBoxLayout()
        section_items.setContentsMargins(0, 0, 0, 0)
        section_items.setSpacing(8)

        qf = _qf()

        # ── 单行工具条：筛选 / 搜索 / 视图开关 / 批量 ─────────
        tool_row = QtWidgets.QHBoxLayout()
        tool_row.setSpacing(6)

        self._date_preset_labels = {"today": "今天", "week": "本周", "month": "本月"}
        self.btn_date_filter = qf["DropDownPushButton"]("时间筛选")
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
        tool_row.addWidget(self.btn_date_filter)

        self.combo_tag = qf["ComboBox"]()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        self.combo_tag.setMinimumWidth(120)
        self.combo_tag.currentIndexChanged.connect(self._load_items)
        tool_row.addWidget(self.combo_tag)

        self.combo_search_field = qf["ComboBox"]()
        self.combo_search_field.addItems(["全部", "标题", "描述", "链接"])
        self.combo_search_field.setFixedWidth(86)
        self.combo_search_field.currentIndexChanged.connect(self._load_items)
        tool_row.addWidget(self.combo_search_field)

        self.search_input = qf["SearchLineEdit"]()
        self.search_input.setPlaceholderText("搜索标题 / 描述 / 链接…")
        self.search_input.setMinimumWidth(120)
        self.search_input.returnPressed.connect(self._load_items)
        self.search_input.searchSignal.connect(self._load_items)
        self.search_input.clearSignal.connect(self._load_items)
        tool_row.addWidget(self.search_input, 1)

        self._current_date_range = None

        self.btn_favorites = qf["ToggleButton"]("仅收藏")
        self.btn_favorites.setCheckable(True)
        self.btn_favorites.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_favorites)

        self.btn_unread = qf["ToggleButton"]("仅未读")
        self.btn_unread.setCheckable(True)
        self.btn_unread.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_unread)

        self.chk_select_all = qf["CheckBox"]("全选")
        self.chk_select_all.stateChanged.connect(self._select_all)
        tool_row.addWidget(self.chk_select_all)

        self.btn_batch_ops = qf["PrimaryDropDownPushButton"]("批量操作")
        self.btn_batch_ops.setToolTip("对选中条目执行批量操作")
        self._batch_menu = qf["RoundMenu"](parent=self)
        self._batch_actions = {}
        _act_read = QtGui.QAction("标记已读", self._batch_menu)
        self._batch_menu.addAction(_act_read)
        _act_read.triggered.connect(self._batch_mark_read)
        self._batch_actions["read"] = _act_read
        _act_unread = QtGui.QAction("标记未读", self._batch_menu)
        self._batch_menu.addAction(_act_unread)
        _act_unread.triggered.connect(self._batch_mark_unread)
        self._batch_actions["unread"] = _act_unread
        _act_delete = QtGui.QAction("删除选中", self._batch_menu)
        self._batch_menu.addAction(_act_delete)
        _act_delete.triggered.connect(self._batch_delete)
        self._batch_actions["delete"] = _act_delete
        self._batch_menu.addSeparator()
        _act_all_read = QtGui.QAction("全部已读", self._batch_menu)
        self._batch_menu.addAction(_act_all_read)
        _act_all_read.triggered.connect(self._mark_all_read)
        self.btn_batch_ops.setMenu(self._batch_menu)
        tool_row.addWidget(self.btn_batch_ops)

        self._update_batch_buttons()
        section_items.addLayout(tool_row)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(3)

        self.item_list = QtWidgets.QListWidget()
        self.item_list.setObjectName("rssItemList")
        self.item_list.setAlternatingRowColors(False)
        self.item_list.viewport().setAutoFillBackground(False)
        self.item_list.setStyleSheet(
            ("QListWidget {{ background: {panel}; border: none; border-radius: 8px; }}"
             "QListWidget::item {{ padding: 2px 4px; border-radius: 6px; }}"
             "QListWidget::item:selected {{ background: {row_selected}; }}"
             "QListWidget::item:hover {{ background: {row_hover}; }}").format(**rss_c)
        )
        self.item_list.itemDoubleClicked.connect(self._open_item)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.itemChanged.connect(self._on_item_changed)
        self.item_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.item_list.customContextMenuRequested.connect(self._show_context_menu)
        splitter.addWidget(self.item_list)

        self._summary_title = QtWidgets.QLabel("点击左侧条目查看摘要…")
        self._summary_title.setWordWrap(True)
        self._summary_title.setStyleSheet(
            "QLabel { font-size: 15px; font-weight: bold; background: transparent; }"
        )
        self._summary_meta = QtWidgets.QLabel("")
        self._summary_meta.setWordWrap(True)
        self._summary_meta.setStyleSheet(
            f"QLabel {{ color: {rss_c['text_secondary']}; font-size: 12px; background: transparent; }}"
        )
        self._summary_desc = QtWidgets.QLabel("")
        self._summary_desc.setWordWrap(True)
        self._summary_desc.setMaximumHeight(120)
        self._summary_desc.setStyleSheet(
            "QLabel { font-size: 12px; background: transparent; }"
        )
        self._summary_desc.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        self._preview_container = QtWidgets.QWidget()
        preview_panel = QtWidgets.QVBoxLayout(self._preview_container)
        preview_panel.setContentsMargins(0, 0, 0, 0)
        preview_panel.setSpacing(4)
        preview_panel.addWidget(self._summary_title)
        preview_panel.addWidget(self._summary_meta)
        preview_panel.addWidget(self._summary_desc)

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
            ("QStackedWidget {{ background: {panel}; border-radius: 8px; }}").format(**rss_c)
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

        splitter.addWidget(self._preview_container)

        splitter.setSizes([500, 300])
        self._preview_splitter = splitter
        section_items.addWidget(splitter, 1)

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

        page_row.addStretch(1)

        self.lb_total = QtWidgets.QLabel("")
        self.lb_total.setStyleSheet(f"color: {_pg_c['text_secondary']}; padding-right: 6px;")
        page_row.addWidget(self.lb_total)

        section_items.addLayout(page_row)

        outer = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer.setHandleWidth(3)
        outer.addWidget(self._sidebar)

        content_wrap = QtWidgets.QWidget()
        content_wrap.setObjectName("rssContentWrap")
        content_wrap.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        content_wrap.setStyleSheet(
            ("QWidget#rssContentWrap {{ background: {panel_soft}; border-radius: 10px; }}").format(**rss_c)
        )
        wrap = QtWidgets.QVBoxLayout(content_wrap)
        wrap.setContentsMargins(12, 12, 12, 12)
        wrap.setSpacing(8)
        wrap.addLayout(section_items)
        outer.addWidget(content_wrap)
        outer.setSizes([240, 900])
        root.addWidget(outer)

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
