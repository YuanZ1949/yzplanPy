"""RSS 侧栏：_RssSidebar（基础构造与初始化）。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .rows import _ElideLabel
from .styles import _btn_primary_style, _rss_btn_group_style, _sidebar_qss
from .text_utils import _qf, _rss_colors

class _SidebarNode(QtWidgets.QWidget):
    """侧栏节点行：彩色圆角徽章 + 名称 + 尾部计数（适配 QListWidget.setItemWidget）。

    徽章支持字符（如 ◉ 全部、◎ 未读、★ 收藏、⇣ 磁链）或 QIcon（聚合 FOLDER / 订阅源图标）。
    控件背景透明，让 QListWidget::item:selected 的高亮背景透出。
    """

    def __init__(self, text, badge_char=None, icon=None, badge_bg="", badge_fg="",
                 count=None, count_color=None, count_bold=False, indent=0, parent=None):
        super().__init__(parent)
        c = _rss_colors()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(4)

        self.badge = QtWidgets.QLabel(badge_char or "")
        self.badge.setFixedSize(16, 16)
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        if icon is not None:
            pm = icon.pixmap(12, 12)
            if not pm.isNull():
                self.badge.setPixmap(pm)
        self.badge.setStyleSheet(
            "QLabel { background: %s; color: %s; border-radius: 6px; font-size: 12px; }"
            % (badge_bg or "transparent", badge_fg or c["text_secondary"])
        )
        lay.addWidget(self.badge)

        display_text = ("· " + text) if indent else text
        self.name_lb = _ElideLabel(display_text)
        self.name_lb.setStyleSheet(
            "QLabel { color: %s; font-size: 12px; background: transparent; }" % c["title_unread"]
        )
        self.name_lb.setToolTip(display_text)
        lay.addWidget(self.name_lb, 1)

        if count is not None:
            fw = "font-weight: 600;" if count_bold else ""
            shown = count
            if isinstance(shown, int) and shown >= 1000:
                ktxt = "%.1fk" % (shown / 1000.0)
                shown = ktxt[:-1] if ktxt.endswith(".0k") else ktxt
            self.count_lb = QtWidgets.QLabel(str(shown))
            self.count_lb.setStyleSheet(
                "QLabel { color: %s; font-size: 11px; background: transparent; %s }"
                % (count_color or c["text_secondary"], fw)
            )
            lay.addWidget(self.count_lb)
        else:
            self.count_lb = None


class _RssSidebar(QtWidgets.QWidget):
    """RSS 侧边栏（平铺）：全部条目 / 手动聚合 / 订阅源，支持排序与增删管理。

    节点选择后通过 page.on_sidebar_selection_changed() 驱动列表刷新。
    """

    SORT_OPTIONS = [
        ("更新时间↓", "updated", True),
        ("更新时间↑", "updated", False),
        ("名称↑", "name", False),
        ("名称↓", "name", True),
        ("添加时间↓", "added", True),
        ("添加时间↑", "added", False),
    ]

    def __init__(self, owner, page, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.page = page
        self._nodes = []
        self._sort_field = "name"
        self._sort_desc = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        # 顶部：添加与管理按钮（图标化，按钮组容器）
        qf = _qf()
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(4)
        btn_group = QtWidgets.QFrame()
        btn_group.setObjectName("rss_btn_group")
        btn_group.setStyleSheet(_rss_btn_group_style())
        bg_lay = QtWidgets.QHBoxLayout(btn_group)
        bg_lay.setContentsMargins(4, 2, 4, 2)
        bg_lay.setSpacing(4)
        self.btn_add_feed = qf["ToolButton"](qf["FluentIcon"].ADD)
        self.btn_add_feed.setToolTip("添加订阅源")
        self.btn_add_feed.setFixedSize(30, 30)
        self.btn_add_feed.clicked.connect(self._add_feed)
        bg_lay.addWidget(self.btn_add_feed)
        self.btn_add_agg = qf["PrimaryToolButton"](qf["FluentIcon"].FOLDER_ADD)
        self.btn_add_agg.setToolTip("添加聚合")
        self.btn_add_agg.setFixedSize(30, 30)
        self.btn_add_agg.clicked.connect(self._add_aggregation)
        bg_lay.addWidget(self.btn_add_agg)
        self.btn_manage_feed = qf["ToolButton"](qf["FluentIcon"].EDIT)
        self.btn_manage_feed.setToolTip("管理订阅源（添加 / 编辑 / 删除 / 启用停用）")
        self.btn_manage_feed.setFixedSize(30, 30)
        self.btn_manage_feed.clicked.connect(self.page._toggle_feed_section)
        bg_lay.addWidget(self.btn_manage_feed)
        top_row.addWidget(btn_group)
        top_row.addStretch(1)
        lay.addLayout(top_row)

        # 排序行
        sort_row = QtWidgets.QHBoxLayout()
        sort_lb = qf["CaptionLabel"]("排序")
        sort_lb.setStyleSheet(f"color: {_rss_colors()['text_secondary']};")
        sort_row.addWidget(sort_lb)
        self.combo_sort = qf["ComboBox"]()
        for label, _f, _d in self.SORT_OPTIONS:
            self.combo_sort.addItem(label)
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.combo_sort, 1)

        # 平铺节点列表
        self.list = QtWidgets.QListWidget()
        self.list.setSpacing(1)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        lay.addWidget(self.list, 1)

        # 排序行固定于列表下方（贴近底部工具区）
        lay.addLayout(sort_row)

        # 概览与状态（刷新/全部刷新上方）
        sidebar_c = _rss_colors()
        self.lb_summary = qf["CaptionLabel"]("")
        self.lb_summary.setWordWrap(True)
        self.lb_summary.setStyleSheet(f"color: {sidebar_c['text_secondary']}; padding: 0 2px;")
        self.lb_status = QtWidgets.QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setStyleSheet(f"color: {sidebar_c['text_faint']}; padding: 0 2px;")

        # 底部工具：统一刷新（下拉多选 + 一键全部刷新）
        bottom_row = QtWidgets.QHBoxLayout()

        self._refresh_ops = {
            "feeds": False,
            "scan": False,
            "icons": False,
            "aggs": False,
        }
        self.btn_refresh = QtWidgets.QToolButton()
        self.btn_refresh.setText("刷新 ▾")
        self.btn_refresh.setMinimumHeight(30)
        self.btn_refresh.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_refresh.setToolTip("选择本次刷新要执行的操作（可多选，执行所选后自动清除）")
        self.refresh_menu = QtWidgets.QMenu(self)
        self._refresh_actions = {}
        self._refresh_actions["feeds"] = self.refresh_menu.addAction("刷新订阅")
        self._refresh_actions["scan"] = self.refresh_menu.addAction("扫描磁力")
        self._refresh_actions["icons"] = self.refresh_menu.addAction("刷新图标")
        self._refresh_actions["aggs"] = self.refresh_menu.addAction("刷新聚合")
        for key, act in self._refresh_actions.items():
            act.setCheckable(True)
            act.toggled.connect(lambda checked, k=key: self._on_refresh_toggle(k, checked))
        self.refresh_menu.addSeparator()
        act_run = self.refresh_menu.addAction("执行所选")
        act_run.triggered.connect(self._run_selected_refresh)
        self.btn_refresh.setMenu(self.refresh_menu)

        self.btn_refresh_all = QtWidgets.QPushButton("全部刷新")
        self.btn_refresh_all.setToolTip("一键刷新：订阅 + 扫描磁力 + 图标 + 聚合")
        self.btn_refresh_all.setMinimumHeight(30)
        self.btn_refresh_all.setStyleSheet(_btn_primary_style())
        self.btn_refresh_all.clicked.connect(self._refresh_all_now)

        bottom_row.addWidget(self.btn_refresh)
        bottom_row.addWidget(self.btn_refresh_all)
        lay.addLayout(bottom_row)

        # 概览与状态（固定在底部工具之下）
        lay.addWidget(self.lb_summary)
        lay.addWidget(self.lb_status)

        # 侧栏面板：透明背景让 page 渐变透出，边框/圆角保留
        _sc = _rss_colors()
        self.setStyleSheet(
            _sidebar_qss()
            + "\n_RssSidebar { background: transparent; border: 1px solid %s; border-radius: 10px; }"
            % (_sc["border"],))
