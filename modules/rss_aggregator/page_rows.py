"""RSS 页面：订阅源列表与条目加载/分页。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .page_actions import _RssPageWidget
from .dialogs_a import _EditFeedDialog
from .rows_item import _make_item_row

PAGE_SIZE = 50

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _load_feeds(self):
        self.feed_list.clear()
        for f in self.owner.store.list_feeds():
            status = "✓" if f["enabled"] else "✗"
            group = f" [{f['group_name']}]" if f.get("group_name") else ""
            error = f" ⚠{f['last_error'][:30]}" if f.get("last_error") else ""
            kind = " [监控]" if f.get("feed_type") == "scrape" else ""
            text = "{}{} {}{}{} — {}{}".format(status, kind, f["name"], group, "", f["url"], error)
            tags = f.get("tags") or ([f["tag"]] if f.get("tag") else [])
            tags = [t for t in tags if t and t != f["name"]]
            if tags:
                text += "  (标签: {})".format(", ".join(tags))
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, f["id"])
            item.setData(QtCore.Qt.UserRole + 1, f["enabled"])
            self.feed_list.addItem(item)

    def _on_feed_order_changed(self):
        feed_ids = []
        for i in range(self.feed_list.count()):
            item = self.feed_list.item(i)
            feed_ids.append(item.data(QtCore.Qt.UserRole))
        self.owner.store.update_feed_order(feed_ids)

    def _edit_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        feed = self.owner.store.get_feed_by_id(fid)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _load_tag_filter(self):
        current = self.combo_tag.currentData()
        self.combo_tag.blockSignals(True)
        self.combo_tag.clear()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        for tag in self.owner.store.list_tags():
            self.combo_tag.addItem(tag, tag)
        if current:
            idx = self.combo_tag.findData(current)
            if idx >= 0:
                self.combo_tag.setCurrentIndex(idx)
        self.combo_tag.blockSignals(False)
        self._sync_filter_menus()

    def _sync_filter_menus(self):
        """顶部「筛选▾」的类型/标签子菜单与 combo_tag 状态保持同步。"""
        if not hasattr(self, "_type_actions"):
            return
        cur = self.combo_tag.currentData()
        for act, data in zip(self._type_actions, (None, "__磁链__", "__文章__")):
            act.blockSignals(True)
            act.setChecked(cur == data)
            act.blockSignals(False)
        if not hasattr(self, "_tag_menu"):
            return
        self._tag_menu.clear()
        tags = [t for t in self.owner.store.list_tags() if t]
        if not tags:
            _empty = QtGui.QAction("暂无标签", self._tag_menu)
            _empty.setEnabled(False)
            self._tag_menu.addAction(_empty)
            return
        _group = QtGui.QActionGroup(self._tag_menu)
        for tag in tags:
            act = QtGui.QAction(tag, self._tag_menu)
            act.setCheckable(True)
            act.setChecked(cur == tag)
            act.triggered.connect(
                lambda _c=False, data=tag: self.combo_tag.setCurrentIndex(
                    max(0, next((i for i in range(self.combo_tag.count())
                                 if self.combo_tag.itemData(i) == data), -1))))
            _group.addAction(act)
            self._tag_menu.addAction(act)

    def _load_items(self, preserve_scroll=False):
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = None
        if preserve_scroll and scrollbar is not None:
            prev_value = scrollbar.value()

        query = self.search_input.text().strip()
        fav_only = self.btn_favorites.isChecked()
        unread_only = self.btn_unread.isChecked()

        field_map = {"全部": None, "标题": "title", "描述": "description", "链接": "link"}
        search_field = field_map.get(self.combo_search_field.currentText())

        if query:
            self._all_items = self.owner.store.search(query, 5000, field=search_field)
            torrent_filter = None
        else:
            tag_filter = self.combo_tag.currentData()
            sel = self._sidebar.current_filter() if hasattr(self, "_sidebar") else {}
            agg_type = sel.get("agg_type")
            if agg_type == "torrent":
                agg_id = sel.get("agg_id")
                self._load_torrent_aggregation(agg_id)
                return
            if agg_type == "similarity":
                agg_id = sel.get("agg_id")
                self._load_similarity_aggregation(agg_id)
                return
            torrent_filter = None
            # 侧栏快捷节点过滤（未读/收藏/磁链）合并进查询
            fav_only = fav_only or bool(sel.get("favorites_only"))
            unread_only = unread_only or bool(sel.get("unread_only"))
            if not tag_filter and sel.get("type_magnet"):
                tag_filter = "__磁链__"
            self._all_items = self.owner.store.recent(
                5000, tag_filter=tag_filter, favorites_only=fav_only, unread_only=unread_only,
                date_range=self._current_date_range,
                feed_ids=sel.get("feed_ids"),
                agg_id=sel.get("agg_id"),
                keyword=sel.get("keyword"),
                torrent_hash=torrent_filter,
            )

        self._load_tag_filter()
        total = len(self._all_items)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._current_page = min(self._current_page, total_pages - 1)
        start = self._current_page * PAGE_SIZE
        page_items = self._all_items[start : start + PAGE_SIZE]

        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        for it in page_items:
            is_checked = it["hash"] in self._selected_hashes
            row_widget, title_btn, chk = _make_item_row(
                self.item_list, it, None, show_thumbnail=self._show_thumbnails, checked=is_checked)
            title_btn.clicked.connect(lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
            chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))

            self._item_title_btns[it["hash"]] = title_btn
            self._item_checkboxes[it["hash"]] = chk

            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            item.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
            item.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
            self.item_list.addItem(item)
            self.item_list.setItemWidget(item, row_widget)

        self.lb_page.setText(f"第 {self._current_page + 1}/{total_pages} 页")
        if torrent_filter:
            srcs = set()
            for it in self._all_items:
                for t in (it.get("tags") or "").split("|"):
                    t = t.strip()
                    if t:
                        srcs.add(t)
            self.lb_total.setText(f"磁链聚合 ◈ {len(srcs)} 个来源 · 共 {total} 条")
        else:
            self.lb_total.setText(f"共 {total} 条")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < total_pages - 1)

        QtCore.QTimer.singleShot(0, self._sync_row_heights)

        if prev_value is not None and scrollbar is not None:
            QtCore.QTimer.singleShot(
                0, lambda sb=scrollbar, v=prev_value, m=(scrollbar.maximum() if scrollbar is not None else 0): sb.setValue(min(v, m))
            )

        self._refresh_header_summary()

    def _sync_row_heights(self):
        """按当前列表宽度重算各行高度，使可换行标题自适应行高，并计入样式内边距避免截断。"""
        if not hasattr(self, "item_list"):
            return
        list_w = self.item_list
        # 条目自身左右留白(item padding 4px*2 + 外边距余量)。
        # style_pad 需覆盖 item padding(4px*2) + item margin(1px*2) + 边框(1px*2)，
        # 否则按过宽的可用宽度计算换行，最后一行会被截断。
        style_pad = 18
        # 纵向同样被 item 内边距压缩：padding(3px*2) + margin(1px*2) + 边框(1px*2) = 10px。
        # 不补偿则行 widget 实际高度比所需少 10px，多行内容上下被截断。
        style_pad_v = 10
        vp_w = list_w.viewport().width() - 8 - style_pad
        if vp_w <= 0:
            vp_w = 400
        for row in range(list_w.count()):
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
            # 保证标题至少完整显示一行，并留底部余量避免截断
            h = max(h, 34)
            item.setSizeHint(QtCore.QSize(vp_w + 8 + style_pad, int(h) + style_pad_v))

    def _sync_summary_desc_height(self):
        """把摘要描述滚动区高度限制为预览列高度的约 40%，
        长描述可滚动完整阅读，同时不把 WebEngine 预览栈挤到零。"""
        if not hasattr(self, "_summary_desc_scroll") or self._summary_desc_scroll is None:
            return
        container = getattr(self, "_preview_container", None)
        if container is None:
            return
        h = int(container.height() * 0.4)
        self._summary_desc_scroll.setMaximumHeight(max(60, h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        QtCore.QTimer.singleShot(0, self._sync_summary_desc_height)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        QtCore.QTimer.singleShot(0, self._sync_summary_desc_height)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_items()

    def _next_page(self):
        total_pages = max(1, (len(self._all_items) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._load_items()
