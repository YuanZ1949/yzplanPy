"""RSS 页面：磁链聚合渲染与头行交互。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_f import _AddAggregationDialog
from .page_rows import _AGG_PAGE_SIZE, _RssPageWidget
from .rows import _HeadRow
from .rows_item import _make_item_row
from .text_utils import _rss_colors

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _load_torrent_aggregation(self, agg_id):
        """磁链hash类型聚合：按 torrent_hash 分组(默认折叠)，按分组头分页渲染。"""
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = scrollbar.value() if scrollbar is not None else None
        groups = self.owner.store.get_aggregation_torrent_groups(agg_id, limit=None)
        # 一次查询获取全部成员条目，按 torrent_hash 分组
        all_members = self.owner.store.get_all_aggregation_torrent_items(agg_id)
        total = sum(g.get("count") or 0 for g in groups)
        self._agg_groups = []
        for g in groups:
            head_hash = g.get("hash") or ""
            head_title = (g.get("title") or "(无标题)")
            srcs = g.get("feed_count") or 0
            self._agg_groups.append({
                "head_key": head_hash,
                "title": head_title,
                "count_text": "{} 来源".format(srcs),
                "members": all_members.get(head_hash, []),
                "head_tooltip": "单击标题=预览该分组\n双击=默认打开一个来源\n单击来源徽标=展开查看全部来源",
                "head_data": f"__agg_head__{head_hash}",
                "title_cb": lambda _=False, h=head_hash, agg=agg_id: self._agg_head_preview(h, agg),
                "open_cb": lambda _=False, h=head_hash, agg=agg_id: self._agg_head_open(h, agg),
                "toggle_cb": lambda _=False, h=head_hash: self._toggle_torrent_group(h),
                "checkbox_cb": lambda checked, h=head_hash: self._on_head_checkbox_toggled(h, checked),
            })
        self._agg_mode = True
        self._agg_page = 0
        self._agg_kind_label = "磁链聚合"
        self._agg_total_items = total
        self._render_agg_page(scrollbar=scrollbar, prev_value=prev_value)

    def _render_agg_page(self, scrollbar=None, prev_value=None):
        """磁链/相似性聚合共享渲染器：按分组头分页，展开/折叠状态跨页保留。"""
        groups = self._agg_groups
        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        self._node_item_by_head = {}
        self._group_children = {}
        self._head_buttons = {}
        self._head_by_member = {}
        if scrollbar is None:
            scrollbar = self.item_list.verticalScrollBar()
        if prev_value is None:
            prev_value = scrollbar.value() if scrollbar is not None else None
        total = self._agg_total_items
        _hc = _rss_colors()
        n_pages = max(1, (len(groups) + _AGG_PAGE_SIZE - 1) // _AGG_PAGE_SIZE)
        self._agg_page = min(max(self._agg_page, 0), n_pages - 1)
        start = self._agg_page * _AGG_PAGE_SIZE
        page_groups = groups[start:start + _AGG_PAGE_SIZE]
        for g in page_groups:
            head_key = g["head_key"]
            group_item = QtWidgets.QListWidgetItem()
            group_item.setData(QtCore.Qt.UserRole, g["head_data"])
            group_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            lbl_head = _HeadRow()
            lbl_head.setToolTip(g["head_tooltip"])
            lbl_head.setText(g["title"])
            lbl_head.set_count(g["count_text"])
            lbl_head.set_expanded(head_key in self._agg_expanded)
            lbl_head.setStyleSheet(
                "QWidget#rssHeadRow { background: transparent; }"
                f"QWidget#rssHeadRow:hover {{ background: {_hc['row_hover']}; border-radius: 8px; }}"
                "QPushButton#rssHeadTitle { text-align:left; border:none; background:transparent; "
                f"color:{_hc['title_unread']}; padding:2px; }}"
                f"QPushButton#rssHeadCount {{ background:{_hc['badge_bg']}; color:{_hc['badge_fg']}; "
                "border-radius:9px; padding:2px 9px; font-size:12px; font-weight:600; }"
                f"QPushButton#rssHeadTitle:hover {{ color:{_hc['accent']}; }}"
                f"QPushButton#rssHeadCount:hover {{ color:{_hc['text_primary']}; background:{_hc['accent_bg']}; }}"
            )
            lbl_head.titleClicked.connect(g["title_cb"])
            lbl_head.badgeClicked.connect(g["toggle_cb"])
            lbl_head.headDoubleClicked.connect(g["open_cb"])
            lbl_head.checkboxToggled.connect(g["checkbox_cb"])
            self.item_list.addItem(group_item)
            self.item_list.setItemWidget(group_item, lbl_head)
            self._node_item_by_head[head_key] = group_item
            self._head_buttons[head_key] = lbl_head
            self._group_children[head_key] = []

            for it in g["members"]:
                row_widget, title_btn, chk = _make_item_row(
                    self.item_list, it, None, show_thumbnail=self._show_thumbnails,
                    checked=it["hash"] in self._selected_hashes)
                title_btn.clicked.connect(
                    lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
                chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))
                chk.toggled.connect(
                    lambda _checked, h=head_key: self._sync_head_checkbox_state(h))
                self._item_title_btns[it["hash"]] = title_btn
                self._item_checkboxes[it["hash"]] = chk
                self._head_by_member[it["hash"]] = head_key
                citem = QtWidgets.QListWidgetItem()
                citem.setData(QtCore.Qt.UserRole, it["hash"])
                citem.setData(QtCore.Qt.UserRole + 1, it["link"])
                citem.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
                citem.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
                self.item_list.addItem(citem)
                self.item_list.setItemWidget(citem, row_widget)
                self.item_list.setRowHidden(self.item_list.row(citem), head_key not in self._agg_expanded)
                self._group_children[head_key].append(citem)
            self._sync_head_checkbox_state(head_key)

        self.lb_page.setText("第 {} / {} 页".format(self._agg_page + 1, n_pages))
        self.btn_prev.setEnabled(self._agg_page > 0)
        self.btn_next.setEnabled(self._agg_page < n_pages - 1)
        self.lb_total.setText(
            "{} ◈ {} 个分组 · 共 {} 条".format(self._agg_kind_label, len(groups), total))
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        if prev_value is not None and scrollbar is not None:
            scrollbar.setValue(min(prev_value, scrollbar.maximum()))

    def _agg_head_preview(self, head_hash, agg_id):
        """单击聚合头标题：预览该分组默认(最相关)的一个来源。"""
        it = self._pick_group_item(agg_id, head_hash)
        if it is None:
            return
        self.owner.store.mark_read(it["hash"])
        self._update_read_appearance(it["hash"], True)
        self._show_preview_by_hash(it["hash"], it["link"])

    def _agg_head_open(self, head_hash, agg_id):
        """双击聚合头：默认找一个来源并在系统浏览器打开。"""
        it = self._pick_group_item(agg_id, head_hash)
        if it is None:
            return
        link = it["link"]
        webbrowser.open(link)
        if it["hash"]:
            self.owner.store.mark_read(it["hash"])
            self._update_read_appearance(it["hash"], True)

    def _pick_group_item(self, agg_id, head_hash):
        """从分组里挑一个默认来源：优先已读次数少/内容更全的，否则取最近一条。"""
        try:
            members = self.owner.store.get_aggregation_torrent_items(agg_id, head_hash)
        except Exception:
            members = []
        if not members:
            return None
        for it in members:
            if it.get("link") and it["link"].lower().startswith(("magnet:", "http")):
                return it
        return members[0]

    def _toggle_torrent_group(self, head_hash):
        # 展开/折叠状态存全局集合，跨页保留
        if head_hash in self._agg_expanded:
            self._agg_expanded.discard(head_hash)
        else:
            self._agg_expanded.add(head_hash)
        self._apply_head_expansion(head_hash)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def _apply_head_expansion(self, head_key):
        """把 _agg_expanded 状态应用到当前页该分组（行隐藏 + 头行箭头）。"""
        expanded = head_key in self._agg_expanded
        group_item = self._group_children.get(head_key)
        if not group_item:
            return
        for citem in group_item:
            self.item_list.setRowHidden(self.item_list.row(citem), not expanded)
        btn = self._head_buttons.get(head_key)
        if btn is not None:
            btn.set_expanded(expanded)

    def _on_head_checkbox_toggled(self, head_hash, checked):
        members = self._group_children.get(head_hash, [])
        for citem in members:
            h = citem.data(QtCore.Qt.UserRole)
            chk = self._item_checkboxes.get(h)
            if chk is not None:
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
                if checked:
                    self._selected_hashes.add(h)
                else:
                    self._selected_hashes.discard(h)
        self._update_batch_buttons()

    def _sync_head_checkbox_state(self, head_hash):
        btn = self._head_buttons.get(head_hash)
        if btn is None:
            return
        members = self._group_children.get(head_hash, [])
        if not members:
            btn.set_check_state(QtCore.Qt.Unchecked)
            return
        checked_count = 0
        total = len(members)
        valid = []
        for citem in members:
            try:
                h = citem.data(QtCore.Qt.UserRole)
            except RuntimeError:
                continue  # 条目已随列表重建被销毁，跳过
            valid.append(citem)
            chk = self._item_checkboxes.get(h)
            if chk is not None and chk.isChecked():
                checked_count += 1
        total = len(valid)
        if checked_count == 0:
            btn.set_check_state(QtCore.Qt.Unchecked)
        elif checked_count == total:
            btn.set_check_state(QtCore.Qt.Checked)
        else:
            btn.set_check_state(QtCore.Qt.PartiallyChecked)

    def _open_aggregation(self, agg_id):
        agg = self.owner.store.get_aggregation(agg_id)
        if not agg:
            return
        # 折叠的磁链聚合：直接展开加载内容
        if agg.get("agg_type") == "torrent":
            self._load_torrent_aggregation(agg_id)
        elif agg.get("agg_type") == "similarity":
            self._load_similarity_aggregation(agg_id)
        else:
            self._load_items()

    def _show_add_feed(self):
        self._toggle_feed_section()

    def _show_add_aggregation(self):
        dlg = _AddAggregationDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._reload_sidebar()
            self.on_sidebar_selection_changed()

    def _show_edit_aggregation(self, agg_id):
        dlg = _AddAggregationDialog(self.owner, self, agg_id=agg_id)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._reload_sidebar()
            self.on_sidebar_selection_changed()

    def _show_add_sub_aggregation(self, agg_id):
        dlg = _AddAggregationDialog(self.owner, self, parent_id=agg_id)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._reload_sidebar()
            self.on_sidebar_selection_changed()
