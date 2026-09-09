"""RSS 页面：磁链聚合渲染与头行交互。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_f import _AddAggregationDialog
from .page_rows import _RssPageWidget
from .rows import _HeadRow
from .rows_item import _make_item_row
from .text_utils import _rss_colors

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _load_torrent_aggregation(self, agg_id):
        """磁链hash类型聚合：方案B —— 每个 torrent_hash 一行(默认折叠)，点开展开成员条目。"""
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = scrollbar.value() if scrollbar is not None else None
        groups = self.owner.store.get_aggregation_torrent_groups(agg_id)
        # 一次查询获取全部成员条目，按 torrent_hash 分组
        all_members = self.owner.store.get_all_aggregation_torrent_items(agg_id)
        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        total = sum(g.get("count") or 0 for g in groups)
        self._agg_group_rows = {}
        self._head_by_member = {}
        for g in groups:
            head_hash = g.get("hash") or ""
            head_title = (g.get("title") or "(无标题)")
            srcs = g.get("feed_count") or 0
            group_item = QtWidgets.QListWidgetItem()
            group_item.setData(QtCore.Qt.UserRole, f"__agg_head__{head_hash}")
            group_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            lbl_head = _HeadRow()
            lbl_head.setToolTip(
                "单击标题=预览该分组\n双击=默认打开一个来源\n单击来源徽标=展开查看全部来源")
            lbl_head.setText(head_title)
            lbl_head.set_count("{} 来源".format(srcs))
            _hc = _rss_colors()
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
            lbl_head.titleClicked.connect(
                lambda _=False, h=head_hash, agg=agg_id: self._agg_head_preview(h, agg))
            lbl_head.badgeClicked.connect(
                lambda _=False, h=head_hash: self._toggle_torrent_group(h))
            lbl_head.headDoubleClicked.connect(
                lambda _=False, h=head_hash, agg=agg_id: self._agg_head_open(h, agg))
            lbl_head.checkboxToggled.connect(
                lambda checked, h=head_hash: self._on_head_checkbox_toggled(h, checked))
            self.item_list.addItem(group_item)
            self.item_list.setItemWidget(group_item, lbl_head)
            self._node_item_by_head[head_hash] = group_item
            self._head_buttons[head_hash] = lbl_head
            self._group_children[head_hash] = []

            members = all_members.get(head_hash, [])
            for it in members:
                row_widget, title_btn, chk = _make_item_row(
                    self.item_list, it, None, show_thumbnail=self._show_thumbnails,
                    checked=it["hash"] in self._selected_hashes)
                title_btn.clicked.connect(lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
                chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))
                chk.toggled.connect(
                    lambda _checked, h=head_hash: self._sync_head_checkbox_state(h))
                self._item_title_btns[it["hash"]] = title_btn
                self._item_checkboxes[it["hash"]] = chk
                self._head_by_member[it["hash"]] = head_hash
                citem = QtWidgets.QListWidgetItem()
                citem.setData(QtCore.Qt.UserRole, it["hash"])
                citem.setData(QtCore.Qt.UserRole + 1, it["link"])
                citem.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
                citem.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
                self.item_list.addItem(citem)
                self.item_list.setItemWidget(citem, row_widget)
                self.item_list.setRowHidden(self.item_list.row(citem), True)
                self._group_children[head_hash].append(citem)
            self._sync_head_checkbox_state(head_hash)

        self.lb_page.setText("第 1 页")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        self.lb_total.setText("磁链聚合 ◈ {} 个分组 · 共 {} 条".format(len(groups), total))
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
        group_item = self._group_children.get(head_hash)
        if group_item is None:
            return
        hidden = self.item_list.isRowHidden(self.item_list.row(group_item[0]))
        for citem in group_item:
            self.item_list.setRowHidden(self.item_list.row(citem), not hidden)
        btn = self._head_buttons.get(head_hash)
        if btn is not None:
            txt = btn.text()
            # 折叠(▸/指向右) <-> 展开(▾/指向下)；用统一记号开头，避免重复前缀
            txt = txt.lstrip("▸ ▾ ▹ ▿ ")
            if hidden:
                btn.setText("▾ " + txt)
            else:
                btn.setText("▸ " + txt)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

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
