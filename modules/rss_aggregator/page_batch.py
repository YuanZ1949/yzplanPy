"""RSS 页面：条目点击/预览/批量操作。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .page_similarity import _RssPageWidget
from .text_utils import _rss_colors

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _on_title_click(self, item_hash, link):
        self.owner.store.mark_read(item_hash)
        self._update_read_appearance(item_hash, True)
        self._show_preview_by_hash(item_hash, link)

    def _on_check_toggled(self, item_hash, checked):
        if checked:
            self._selected_hashes.add(item_hash)
        else:
            self._selected_hashes.discard(item_hash)
        self._update_batch_buttons()

    def _on_item_changed(self, item):
        pass

    def _on_item_clicked(self, item):
        h = item.data(QtCore.Qt.UserRole)
        if isinstance(h, str) and h.startswith("__agg_head__"):
            return  # 聚合头点击由头部自身的标题/徽标事件负责
        link = item.data(QtCore.Qt.UserRole + 1)
        if h:
            self.owner.store.mark_read(h)
            self._update_read_appearance(h, True)
        self._show_preview(item)
        self._last_clicked_row = self.item_list.row(item)
        self._sync_row_selected(item)

    def _sync_row_selected(self, item):
        """按点击条目切换行级 selected 属性，驱动 QWidget#rssItemRow[selected=true] 边框态。"""
        clicked_wg = self.item_list.itemWidget(item)
        if clicked_wg is None:
            return
        for i in range(self.item_list.count()):
            it = self.item_list.item(i)
            w = self.item_list.itemWidget(it)
            if w is None:
                continue
            if w is clicked_wg and not it.isSelected():
                self.item_list.setCurrentItem(it)
            selected = w is clicked_wg
            if bool(w.property("selected")) != selected:
                w.setProperty("selected", selected)
                w.style().unpolish(w)
                w.style().polish(w)

    def _update_read_appearance(self, item_hash, is_read):
        btn = self._item_title_btns.get(item_hash)
        if btn is not None:
            c = _rss_colors()
            dot = getattr(btn, "_rss_dot", None)
            if dot is not None:
                dot.setStyleSheet(
                    f"QLabel {{ color: {c['dot_unread' if not is_read else 'dot_read']}; font-size: 10px; }}")
            if is_read:
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; border: none; background: transparent; "
                    f"color: {c['title_read']}; padding: 2px; }}"
                    f"QPushButton:hover {{ color: {c['text_secondary']}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; border: none; background: transparent; color: {c['title_unread']}; "
                    "font-weight: 600; padding: 2px; }"
                    f"QPushButton:hover {{ color: {c['accent']}; }}"
                )

    def _show_preview(self, item):
        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)
        img_url = item.data(QtCore.Qt.UserRole + 3)
        if not h:
            return
        item_data = self.owner.store.get_item(h)
        if not item_data:
            return
        if img_url and not item_data.get("image_url"):
            item_data = dict(item_data)
            item_data["image_url"] = img_url
        self._preview_link = link
        self._display_preview(item_data, link)

    def _show_preview_by_hash(self, item_hash, link):
        item_data = self.owner.store.get_item(item_hash)
        if not item_data:
            return
        self._preview_link = link
        self._display_preview(item_data, link)


    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        h = item.data(QtCore.Qt.UserRole)
        if isinstance(h, str) and h.startswith("__agg_head__"):
            return  # 聚合头双击由头部自身处理
        if link:
            self.owner.store.mark_read(h)
            self._update_read_appearance(h, True)
            self._show_preview(item)

    def _select_all(self, state):
        checked = state == QtCore.Qt.CheckState.Checked.value
        sel = self._sidebar.current_filter() if hasattr(self, "_sidebar") else {}
        if sel.get("agg_type") in ("torrent", "similarity"):
            # 磁链/相似性分组：成员复选框已全部存在（含折叠隐藏的），直接遍历复选框
            for item_hash, chk in self._item_checkboxes.items():
                chk.setChecked(checked)
        else:
            # 普通列表：跨页全选整个查询结果集
            for it in self._all_items:
                if checked:
                    self._selected_hashes.add(it["hash"])
                else:
                    self._selected_hashes.discard(it["hash"])
            # 同步当前页可见的复选框（阻断信号，避免重复更新集合）
            for item_hash, chk in self._item_checkboxes.items():
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
        for head_hash in self._group_children:
            self._sync_head_checkbox_state(head_hash)
        self._update_batch_buttons()

    def _get_selected_hashes(self):
        return list(self._selected_hashes)

    def _update_batch_buttons(self):
        count = len(self._selected_hashes)
        for key in ("read", "unread", "delete"):
            self._batch_actions[key].setEnabled(count > 0)
        self.btn_batch_ops.setText(f"批量 ({count})" if count else "批量")

    def _invert_selection(self):
        sel = self._sidebar.current_filter() if hasattr(self, "_sidebar") else {}
        if sel.get("agg_type") in ("torrent", "similarity"):
            # 磁链/相似性分组：成员复选框已全部存在（含折叠隐藏的），逐个取反
            for item_hash, chk in self._item_checkboxes.items():
                chk.setChecked(not chk.isChecked())
        else:
            # 普通列表：跨页反选整个查询结果集
            cur = set(self._selected_hashes)
            new_sel = [it["hash"] for it in self._all_items if it["hash"] not in cur]
            self._selected_hashes = set(new_sel)
            # 同步当前页可见的复选框（阻断信号，避免重复更新集合）
            for item_hash, chk in self._item_checkboxes.items():
                chk.blockSignals(True)
                chk.setChecked(item_hash in new_sel)
                chk.blockSignals(False)
        for head_hash in self._group_children:
            self._sync_head_checkbox_state(head_hash)
        self._update_batch_buttons()

    def _clear_selection(self):
        self._select_all(QtCore.Qt.CheckState.Unchecked.value)

    def _batch_mark_read(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_read(hashes)
            for h in hashes:
                self._update_read_appearance(h, True)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_mark_unread(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_unread(hashes)
            for h in hashes:
                self._update_read_appearance(h, False)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_delete(self):
        hashes = self._get_selected_hashes()
        if hashes:
            reply = QtWidgets.QMessageBox.question(
                self, "确认删除", f"确定删除 {len(hashes)} 条记录？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.owner.store.batch_delete(hashes)
                self._selected_hashes.clear()
                self._load_items()

    def _mark_all_read(self):
        tag_filter = self.combo_tag.currentData()
        self.owner.store.mark_all_read(tag_filter)
        self._load_items(preserve_scroll=True)
