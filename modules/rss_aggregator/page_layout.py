"""RSS 页面：三栏主体构建与整体编排。"""

from core.perf import timed
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .page import _RssPageWidget
from .sidebar_actions import _RssSidebar
from .styles import _btn_style, _sidebar_qss
from .text_utils import _rss_colors


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _build_ui(self, rss_c):
        """构建页面全部控件（一次性调用，避免重复创建）。"""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._build_tool_bar(rss_c, root)
        self._build_three_col(rss_c, root)

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
        # 主题切换动态刷新：构建时应用一次，之后跟随 QApplication.paletteChanged
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._apply_theme)
        self._apply_theme()

    def _build_three_col(self, rss_c, root):
        """三栏主体：侧栏 | 拖拽 | 列表 | 拖拽 | 预览。"""
        # 创建三栏容器
        self._three_col = QtWidgets.QHBoxLayout()
        self._three_col.setContentsMargins(0, 8, 0, 0)
        self._three_col.setSpacing(0)
        # 三栏宽度（像素），供拖拽手柄调整；None 表示跟随布局自动分配
        self._side_width = None
        self._list_width = None
        self._preview_width = None
        self._drag_active = False

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
        self._side_col = _side_col
        self._three_col.addWidget(_side_col, 0)

        # 拖拽手柄1
        self._grip1 = self._make_grip(1)
        self._three_col.addWidget(self._grip1)

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
             "QListWidget::item {{ margin: 1px 3px; padding: 3px 5px; border-radius: 6px; "
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

        self._list_col = _list_col
        self._three_col.addWidget(_list_col, 1)

        # 拖拽手柄2
        self._grip2 = self._make_grip(2)
        self._three_col.addWidget(self._grip2)

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
        self._summary_desc.setStyleSheet(
            f"QLabel {{ font-size: 12.5px; background: transparent; color: {rss_c['text']}; line-height: 1.7; }}"
        )
        self._summary_desc.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        # 描述可滚动：长描述完整可读，同时用有界高度避免把 WebEngine 预览栈挤到零。
        self._summary_desc_scroll = QtWidgets.QScrollArea()
        self._summary_desc_scroll.setWidgetResizable(True)
        self._summary_desc_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._summary_desc_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._summary_desc_scroll.setWidget(self._summary_desc)
        self._summary_desc_scroll.setMaximumHeight(120)

        # 预览分隔线
        _sep_line = QtWidgets.QWidget()
        _sep_line.setFixedHeight(1)
        _sep_line.setStyleSheet(f"background: {rss_c['border']};")
        self._sep_line = _sep_line

        self._preview_container = QtWidgets.QWidget()
        preview_panel = QtWidgets.QVBoxLayout(self._preview_container)
        preview_panel.setContentsMargins(8, 4, 8, 4)
        preview_panel.setSpacing(6)
        preview_panel.addWidget(self._summary_status)
        preview_panel.addWidget(self._summary_title)
        preview_panel.addWidget(self._summary_meta)
        preview_panel.addWidget(self._summary_desc_scroll)
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

        self._preview_col = _preview_col
        self._three_col.addWidget(_preview_col, 1)

        # 恢复上次拖拽保存的三栏宽度比例（rss.col_widths）
        self._restore_col_widths()

        root.addLayout(self._three_col, 1)