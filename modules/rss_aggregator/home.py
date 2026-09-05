"""RSS 首页部件：_RssHomeWidget。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .text_utils import _qf, _rss_colors
from ..rss_store import _is_magnet_or_torrent

logger = logging.getLogger("rss_aggregator")

class _RssHomeWidget(QtWidgets.QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        header = QtWidgets.QHBoxLayout()
        _lc = _rss_colors()
        qf = _qf()
        lb_home_icon = qf["IconWidget"](qf["FluentIcon"].GLOBE)
        lb_home_icon.setFixedSize(22, 22)
        lb_home_icon.setStyleSheet(f"background: {_lc['accent_bg']}; border-radius: 6px;")
        header.addWidget(lb_home_icon)
        lb_home_title = QtWidgets.QLabel("RSS 聚合")
        lb_home_title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {_lc['title_unread']};")
        header.addWidget(lb_home_title)
        header.addStretch(1)

        self.lb_unread = QtWidgets.QLabel("")
        self.lb_unread.setStyleSheet(f"QLabel {{ color: {_lc['accent']}; font-weight: bold; }}")
        header.addWidget(self.lb_unread)

        self.spin_limit = QtWidgets.QSpinBox()
        self.spin_limit.setRange(100, 1000000)
        self.spin_limit.setSingleStep(1000)
        self.spin_limit.setPrefix("显示上限: ")
        self.spin_limit.setSuffix(" 条")
        self.spin_limit.setValue(self.owner.context.config.get("rss.home_limit", 100000))
        self.spin_limit.valueChanged.connect(self._on_limit_changed)
        header.addWidget(self.spin_limit)
        lay.addLayout(header)

        filter_row = QtWidgets.QHBoxLayout()
        self.combo_filter = qf["ComboBox"]()
        self.combo_filter.addItem("全部", None)
        self.combo_filter.addItem("未读", "unread")
        self.combo_filter.addItem("收藏", "favorite")
        self.combo_filter.addItem("磁链", "__磁链__")
        self.combo_filter.addItem("文章", "__文章__")
        self.combo_filter.currentIndexChanged.connect(self._load_items)
        filter_row.addWidget(self.combo_filter)
        filter_row.addStretch(1)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._load_items)
        filter_row.addWidget(self.search_input)
        lay.addLayout(filter_row)

        self.lb_list = QtWidgets.QListWidget()
        self.lb_list.itemDoubleClicked.connect(self._open_item)
        self.lb_list.itemClicked.connect(self._mark_read)
        lay.addWidget(self.lb_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn = qf["PrimaryPushButton"]("立即刷新")
        self.btn.clicked.connect(owner.refresh_now)
        btn_row.addWidget(self.btn)

        self.btn_mark_all = qf["PushButton"]("全部已读")
        self.btn_mark_all.clicked.connect(self._mark_all_read)
        btn_row.addWidget(self.btn_mark_all)
        lay.addLayout(btn_row)

    def _on_limit_changed(self, val):
        self.owner.context.config.set("rss.home_limit", val)
        self._load_items()

    def on_refreshed(self, counts):
        self._load_items()

    def on_feed_done(self, info):
        self._load_items()

    def on_hash_scan_done(self, scanned):
        self._load_items()

    def on_favicons_loaded(self):
        self._load_items()

    def _load_items(self):
        query = self.search_input.text().strip()
        if query:
            items = self.owner.store.search(query, self.spin_limit.value())
        else:
            fav = self.combo_filter.currentData() == "favorite"
            unread = self.combo_filter.currentData() == "unread"
            tag = self.combo_filter.currentData() if self.combo_filter.currentData() not in ("favorite", "unread") else None
            items = self.owner.store.recent(self.spin_limit.value(), tag_filter=tag, favorites_only=fav, unread_only=unread)
        self.lb_list.clear()
        for it in items:
            tags = it["tags"] or ""
            type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"
            is_read = bool(it.get("read"))
            is_fav = bool(it.get("favorite"))
            prefix = "  " if is_read else ""
            fav_mark = "★ " if is_fav else ""
            text = "{}{}[{}] {} [{}]".format(prefix, fav_mark, tags, it["title"], type_tag)
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            if is_read:
                item.setForeground(QtGui.QColor(_rss_colors()["title_read"]))
            self.lb_list.addItem(item)
        unread = self.owner.store.get_unread_count()
        self.lb_unread.setText(f"未读: {unread}" if unread else "")

    def _mark_read(self, item):
        h = item.data(QtCore.Qt.UserRole)
        if h:
            self.owner.store.mark_read(h)
            item.setForeground(QtGui.QColor(_rss_colors()["title_read"]))

    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        if link:
            webbrowser.open(link)

    def _mark_all_read(self):
        self.owner.store.mark_all_read()
        self._load_items()
