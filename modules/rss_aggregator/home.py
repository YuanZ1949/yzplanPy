"""RSS 首页部件：_RssHomeWidget。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .rows_item import _make_item_row
from .text_utils import _qf, _rss_colors

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
        self.lb_unread.setStyleSheet(
            f"QLabel {{ background: {_lc['pill_tag_bg']}; color: {_lc['title_unread']}; "
            "padding: 3px 10px; border-radius: 10px; font-weight: 600; }")
        self.lb_unread.hide()
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
        self._item_title_btns = {}
        self._render_gen = 0
        self._layout_gen = 0
        self._heights_idx = 0
        self._pending_items = []
        self._render_idx = 0
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
        # spinbox 连续点击 valueChanged 会密集触发：合并为一次最终加载，
        # 避免每次点击都全量重建全部行卡片导致主线程阻塞。
        self._schedule_load()

    def on_refreshed(self, counts):
        self._schedule_load()

    def on_feed_done(self, info):
        self._schedule_load()

    def on_hash_scan_done(self, scanned):
        self._schedule_load()

    def on_favicons_loaded(self):
        self._schedule_load()

    def _schedule_load(self):
        """风暴合并：后台刷新每源完成/聚合广播都会触发全量重建，
        密集触发时合并为一次最终刷新（250ms 去抖），避免主线程被布局计算拖死。"""
        if getattr(self, "_load_timer", None) is None:
            self._load_timer = QtCore.QTimer(self)
            self._load_timer.setSingleShot(True)
            self._load_timer.setInterval(250)
            self._load_timer.timeout.connect(self._load_items)
        self._load_timer.start()

    def _load_items(self):
        query = self.search_input.text().strip()
        if query:
            items = self.owner.store.search(query, self.spin_limit.value())
        else:
            fav = self.combo_filter.currentData() == "favorite"
            unread = self.combo_filter.currentData() == "unread"
            tag = self.combo_filter.currentData() if self.combo_filter.currentData() not in ("favorite", "unread") else None
            items = self.owner.store.recent(self.spin_limit.value(), tag_filter=tag, favorites_only=fav, unread_only=unread)
        # 分块渲染：T3 卡片化后每行是自定义 widget（wordWrap QLabel + 布局），
        # 单次重建上千行会阻塞主线程数秒。按块分批建行，块间让出事件循环，
        # 新请求通过 _render_gen 递增主动取消未完成的旧渲染链。
        self.lb_list.clear()
        self._item_title_btns = {}
        self._render_gen += 1
        self._pending_items = items
        self._render_idx = 0
        self._render_chunk()

    def _render_chunk(self):
        gen = self._render_gen
        items = self._pending_items
        idx = self._render_idx
        chunk = min(idx + 100, len(items))
        for it in items[idx:chunk]:
            row_widget, title_btn, _chk = _make_item_row(self.lb_list, it, None)
            title_btn.clicked.connect(lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
            title_btn._rss_dot._rss_link = it["link"]
            title_btn._rss_dot.installEventFilter(self)
            title_btn.label._rss_link = it["link"]
            title_btn.label.installEventFilter(self)
            self._item_title_btns[it["hash"]] = title_btn

            row_item = QtWidgets.QListWidgetItem()
            row_item.setData(QtCore.Qt.UserRole, it["hash"])
            row_item.setData(QtCore.Qt.UserRole + 1, it["link"])
            self.lb_list.addItem(row_item)
            self.lb_list.setItemWidget(row_item, row_widget)
        self._render_idx = chunk
        if chunk >= len(items):
            self._render_finish()
        elif gen == self._render_gen:
            QtCore.QTimer.singleShot(0, self._render_chunk)

    def _render_finish(self):
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        unread = self.owner.store.get_unread_count()
        if unread:
            self.lb_unread.setText(f"未读: {unread}")
            self.lb_unread.show()
        else:
            self.lb_unread.setText("")
            self.lb_unread.hide()

    def _sync_row_heights(self):
        """按当前列表宽度重算各行高度（复用 page_rows 的自适应行高逻辑）。
        高度计算（QLabel.heightForWidth）对上千行同样昂贵，分块执行避免阻塞。"""
        self._layout_gen += 1
        self._heights_idx = 0
        self._sync_heights_chunk()

    def _sync_heights_chunk(self):
        gen = self._layout_gen
        list_w = self.lb_list
        style_pad = 8
        vp_w = list_w.viewport().width() - 8 - style_pad
        if vp_w <= 0:
            vp_w = 400
        idx = self._heights_idx
        end = min(idx + 100, list_w.count())
        for row in range(idx, end):
            item = list_w.item(row)
            wid = list_w.itemWidget(item)
            if wid is None:
                continue
            h = None
            try:
                if wid.hasHeightForWidth():
                    h = wid.heightForWidth(vp_w)
            except Exception:
                h = None
            if not h or h <= 0:
                h = wid.sizeHint().height()
            h = max(h, 40)
            item.setSizeHint(QtCore.QSize(vp_w + 8 + style_pad, int(h)))
        self._heights_idx = end
        if end < list_w.count() and gen == self._layout_gen:
            QtCore.QTimer.singleShot(0, self._sync_heights_chunk)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def _on_title_click(self, h, link):
        """单击标题：标记已读（保持原 itemClicked 语义）。"""
        if h:
            self.owner.store.mark_read(h)
            btn = self._item_title_btns.get(h)
            if btn is not None:
                c = _rss_colors()
                btn.setStyleSheet(
                    f"QLabel {{ text-align: left; border: none; background: transparent; "
                    f"color: {c['title_read']}; padding: 2px; }}"
                    f"QLabel:hover {{ color: {c['text_secondary']}; }}"
                )

    def eventFilter(self, obj, event):
        """双击标题/未读点：打开链接（保持原 itemDoubleClicked 语义）。"""
        if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            link = getattr(obj, "_rss_link", None)
            if link:
                webbrowser.open(link)
                return True
        return super().eventFilter(obj, event)

    def _mark_all_read(self):
        self.owner.store.mark_all_read()
        self._load_items()
