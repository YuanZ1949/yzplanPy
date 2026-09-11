"""RSS 首页部件：_RssHomeWidget。"""

import logging
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .rows_item import _make_item_row
from .text_utils import _qf, _rss_colors

logger = logging.getLogger("rss_aggregator")

# 虚拟化渲染参数：列表数据量可达数千条，但同一时刻只构建
# 「可视区 ± 缓冲」范围内的行 widget（约百个），滚动时增量渲染/销毁。
# 这样滚动条/总行数保持完整语义，同时主线程上的 widget 数量恒定，
# 彻底消除「全量重建海量行 → 事件循环被渲染链打满 → UI 冻结」的路径。
_WINDOW_BUF = 20          # 可视区上下各预留的缓冲行数（滚动预取）
_INITIAL_RENDER = 50      # 首次加载至少渲染的行数（含缓冲预取）
_DEFAULT_ROW_H = 44       # 未渲染行的默认高度（滚动条近似用）
_SETTLE_MS = 40           # 滚动结束防抖：停止滚动后才刷新渲染窗口
_RESIZE_MS = 200          # 窗口尺寸变化防抖：合并连续 resize


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
        self._load_gen = 0
        self._pending_items = []
        self._window_first = 0      # 当前已渲染窗口起点（含）
        self._window_last = -1      # 当前已渲染窗口终点（含）
        self._scroll_timer = QtCore.QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(_SETTLE_MS)
        self._scroll_timer.timeout.connect(self._update_window)
        self._resize_timer = QtCore.QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_MS)
        self._resize_timer.timeout.connect(self._sync_visible_heights)
        # 滚动停止后才刷新渲染窗口：滚动过程中不反复重建行 widget
        self.lb_list.verticalScrollBar().valueChanged.connect(self._on_scroll)
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
        # spinbox 连续点击 valueChanged 会密集触发：合并为一次最终加载。
        self._schedule_load()

    def on_refreshed(self, counts):
        self._schedule_load(restore_scroll=True)

    def on_feed_done(self, info):
        # 失败源（error 非空）不触发加载：失败重试风暴不应打扰列表。
        if not info or info.get("error"):
            return
        # 顶部上下文走即时刷新（重建已轻量化，等效「新条目插入头部」）；
        # 深层浏览时不打断阅读，交给 250ms 去抖合并。
        if self._incremental_ok():
            self._load_items(restore_scroll=True)
        else:
            self._schedule_load(restore_scroll=True)

    def on_hash_scan_done(self, scanned):
        self._schedule_load(restore_scroll=True)

    def on_favicons_loaded(self):
        self._schedule_load(restore_scroll=True)

    def _schedule_load(self, restore_scroll=False):
        """风暴合并：后台刷新每源完成/聚合广播都会触发加载，
        密集触发时合并为一次最终刷新（250ms 去抖）。"""
        self._restore_scroll = restore_scroll or getattr(self, "_restore_scroll", False)
        if getattr(self, "_load_timer", None) is None:
            self._load_timer = QtCore.QTimer(self)
            self._load_timer.setSingleShot(True)
            self._load_timer.setInterval(250)
            self._load_timer.timeout.connect(self._flush_load)
        self._load_timer.start()

    def _flush_load(self):
        self._load_items(restore_scroll=getattr(self, "_restore_scroll", False))

    def _incremental_ok(self):
        """是否处于「顶部实时看新」上下文：无搜索词、"全部"视图、滚动条在顶部附近。"""
        if self.search_input.text().strip():
            return False
        if self.combo_filter.currentData() is not None:
            return False
        if not self.lb_list.count():
            return False
        return self.lb_list.verticalScrollBar().value() <= _INITIAL_RENDER

    def _load_items(self, restore_scroll=False):
        query = self.search_input.text().strip()
        if query:
            items = self.owner.store.search(query, self.spin_limit.value())
        else:
            fav = self.combo_filter.currentData() == "favorite"
            unread = self.combo_filter.currentData() == "unread"
            tag = self.combo_filter.currentData() if self.combo_filter.currentData() not in ("favorite", "unread") else None
            items = self.owner.store.recent(self.spin_limit.value(), tag_filter=tag, favorites_only=fav, unread_only=unread)
        list_w = self.lb_list
        # 记录当前顶部可见条目：刷新（非用户手动切换）时重建后恢复滚动位置
        top_hash = None
        sb = list_w.verticalScrollBar()
        if restore_scroll and sb.value() > 0:
            top_item = list_w.itemAt(QtCore.QPoint(2, 2))
            if top_item is not None:
                top_hash = top_item.data(QtCore.Qt.UserRole)
        self._load_gen += 1
        self._pending_items = items
        self._item_title_btns = {}
        self._window_first = 0
        self._window_last = -1
        # 全量重建「轻量 item」（无 widget）：保证滚动条总行数语义，成本毫秒级。
        # 行 widget 由 _update_window/_render_row 按需构建，同一时刻仅窗口内存活。
        list_w.setUpdatesEnabled(False)
        try:
            list_w.clear()
            for it in items:
                qi = QtWidgets.QListWidgetItem()
                qi.setData(QtCore.Qt.UserRole, it["hash"])
                qi.setData(QtCore.Qt.UserRole + 1, it["link"])
                qi.setSizeHint(QtCore.QSize(0, _DEFAULT_ROW_H))
                list_w.addItem(qi)
        finally:
            list_w.setUpdatesEnabled(True)
        # 恢复滚动位置（O(n) 折叠查询，几毫秒）
        if top_hash is not None:
            for r in range(list_w.count()):
                if list_w.item(r).data(QtCore.Qt.UserRole) == top_hash:
                    list_w.scrollToItem(list_w.item(r), QtWidgets.QAbstractItemView.PositionAtTop)
                    break
        n = list_w.count()
        if n <= 0:
            self._update_unread()
            return
        first_v, last_v = self._visible_range()
        if first_v is None or last_v is None:
            first_v, last_v = 0, 0
        first = max(0, first_v - _WINDOW_BUF)
        last = min(n - 1, max(last_v + _WINDOW_BUF, _INITIAL_RENDER - 1))
        self._apply_window(first, last)
        self._sync_visible_heights()
        self._update_unread()

    def _visible_range(self):
        """返回视口内首尾行索引；视口未布局（隐藏/未显示）时返回 (None, None)。"""
        list_w = self.lb_list
        vp = list_w.viewport()
        if list_w.count() <= 0 or vp.width() <= 0 or vp.height() <= 0:
            return None, None
        top_item = list_w.itemAt(QtCore.QPoint(2, 2))
        bot_item = list_w.itemAt(QtCore.QPoint(2, max(vp.height() - 2, 2)))
        if top_item is None and bot_item is None:
            return None, None
        fi = list_w.row(top_item) if top_item is not None else 0
        li = list_w.row(bot_item) if bot_item is not None else fi
        if fi > li:
            fi, li = li, fi
        if li < 0:
            return None, None
        return fi, li

    def _update_window(self):
        """滚动停止后：按当前可视区 ± 缓冲刷新渲染窗口。"""
        if self._load_gen <= 0:
            return
        n = self.lb_list.count()
        if n <= 0:
            return
        first_v, last_v = self._visible_range()
        if first_v is None or last_v is None:
            return
        first = max(0, first_v - _WINDOW_BUF)
        last = min(n - 1, last_v + _WINDOW_BUF)
        self._apply_window(first, last)

    def _apply_window(self, first, last):
        """增量应用渲染窗口 [first, last]：进入范围的行建 widget，退出范围的行销毁。"""
        owf, owl = self._window_first, self._window_last
        if first < owf:
            for r in range(first, owf):
                self._render_row(r)
            self._window_first = first
        elif first > owf:
            for r in range(owf, first):
                self._destroy_row(r)
            self._window_first = first
        if last > owl:
            for r in range(owl + 1, last + 1):
                self._render_row(r)
            self._window_last = last
        elif last < owl:
            for r in range(last + 1, owl + 1):
                self._destroy_row(r)
            self._window_last = last

    def _render_row(self, row):
        gen = self._load_gen
        if gen != self._load_gen or row >= len(self._pending_items):
            return
        list_w = self.lb_list
        it = self._pending_items[row]
        item = list_w.item(row)
        if item is None or list_w.itemWidget(item) is not None:
            return
        row_widget, title_btn, _chk = _make_item_row(list_w, it, None)
        h = it["hash"]
        title_btn.clicked.connect(lambda _=False, hh=h, link=it["link"]: self._on_title_click(hh, link))
        title_btn._rss_dot._rss_link = it["link"]
        title_btn._rss_dot.installEventFilter(self)
        title_btn.label._rss_link = it["link"]
        title_btn.label.installEventFilter(self)
        self._item_title_btns[h] = title_btn
        list_w.setItemWidget(item, row_widget)
        self._set_row_height(row)

    def _destroy_row(self, row):
        """销毁窗口外的行：移除 widget（Qt 自动销毁并解除事件过滤器），
        恢复默认高度，并从标题按钮字典摘除引用，防止悬垂访问。"""
        list_w = self.lb_list
        item = list_w.item(row)
        if item is None:
            return
        if list_w.itemWidget(item) is not None:
            h = item.data(QtCore.Qt.UserRole)
            if h is not None:
                self._item_title_btns.pop(h, None)
            list_w.setItemWidget(item, None)
        item.setSizeHint(QtCore.QSize(0, _DEFAULT_ROW_H))

    def _set_row_height(self, row):
        """按当前列表宽度计算单行真实高度（复用自适应行高逻辑）。"""
        list_w = self.lb_list
        item = list_w.item(row)
        if item is None:
            return
        wid = list_w.itemWidget(item)
        if wid is None:
            return
        style_pad = 8
        style_pad_v = 12
        vp_w = list_w.viewport().width() - 8 - style_pad
        if vp_w <= 0:
            vp_w = 400
        try:
            if wid.hasHeightForWidth():
                h = wid.heightForWidth(vp_w)
            else:
                h = wid.sizeHint().height()
        except Exception:
            h = None
        if not h or h <= 0:
            h = wid.sizeHint().height()
        h = max(h, 40)
        item.setSizeHint(QtCore.QSize(vp_w + 8 + style_pad, int(h) + style_pad_v))

    def _sync_visible_heights(self):
        """宽高变化后：只重算「可视区 ± 缓冲」即渲染窗口内行的高度。
        未渲染行保持统一默认高度，无需任何计算。"""
        gen = self._load_gen
        if gen != self._load_gen:
            return
        n = self.lb_list.count()
        if n == 0:
            return
        first_v, last_v = self._visible_range()
        if first_v is None or last_v is None:
            first_v, last_v = self._window_first, self._window_last
        lo = max(first_v - _WINDOW_BUF, self._window_first, 0)
        hi = min(last_v + _WINDOW_BUF, self._window_last, n - 1)
        if lo > hi:
            return
        for r in range(lo, hi + 1):
            self._set_row_height(r)

    def _update_unread(self):
        unread = self.owner.store.get_unread_count()
        if unread:
            self.lb_unread.setText(f"未读: {unread}")
            self.lb_unread.show()
        else:
            self.lb_unread.setText("")
            self.lb_unread.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 宽度变化影响行高、视口变化影响可见范围：合并为防抖后各执行一次
        self._resize_timer.start()
        self._scroll_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._resize_timer.start()
        self._scroll_timer.start()

    def _on_scroll(self, value):
        self._scroll_timer.start()

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