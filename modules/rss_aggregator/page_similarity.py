"""RSS 页面：相似性聚合渲染与头行交互（二级聚合）。

在现有聚合基础上，把成员条目按标题相似度聚成若干簇，每簇一行（默认折叠），
点开展开查看该簇内的相似条目 —— 即「在特定聚合条目下查看进一步聚合的内容」。
"""

import logging
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .page_torrent import _RssPageWidget
from .rows import _HeadRow
from .rows_item import _make_item_row
from .text_utils import _cluster_by_similarity_gen, _rss_colors

# 相似度阈值：标题相似度 >= 该值归入同一簇（0~1）
SIMILARITY_THRESHOLD = 0.55

# 聚类分块大小：每处理这么多条目让出一次事件循环，避免大数据量下阻塞主线程。
# 实测 2887 条时每 50 条约 84ms（最大 116ms），界面保持流畅。
_CLUSTER_CHUNK = 50


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _load_similarity_aggregation(self, agg_id):
        """相似性类型聚合：按标题相似度聚簇，每簇一行(默认折叠)，点开展开成员条目。

        聚类在 GUI 线程分块执行（每块让出事件循环），避免大数据量（数千条）
        下长时间阻塞主线程导致界面冻结。
        """
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = scrollbar.value() if scrollbar is not None else None
        # 复用磁链聚合的整组查询：返回 {torrent_hash: [items]}，非磁链条目落在 "" 组。
        grouped = self.owner.store.get_all_aggregation_torrent_items(agg_id)
        all_members = []
        for _th, items in grouped.items():
            all_members.extend(items)
        total = len(all_members)

        # 分块消费聚类生成器：每处理 _CLUSTER_CHUNK 条让出一次事件循环，
        # 保持界面响应；聚类完成后渲染。
        self._sim_cluster_gen = _cluster_by_similarity_gen(
            all_members, SIMILARITY_THRESHOLD)
        self._sim_cluster_total = total
        self._sim_cluster_scrollbar = scrollbar
        self._sim_cluster_prev_value = prev_value
        self._sim_cluster_chunk()

    def _sim_cluster_chunk(self):
        """消费聚类生成器的一个分块，块间让出事件循环。"""
        gen = getattr(self, "_sim_cluster_gen", None)
        if gen is None:
            return
        try:
            for _ in range(_CLUSTER_CHUNK):
                next(gen)
        except StopIteration as e:
            clusters = e.value
            self._sim_cluster_gen = None
            self._render_similarity_clusters(clusters)
            return
        # 未完成：让出事件循环后继续下一块
        QtCore.QTimer.singleShot(0, self._sim_cluster_chunk)

    def _render_similarity_clusters(self, clusters):
        """把聚类结果渲染为折叠分组行 + 成员条目。"""
        scrollbar = self._sim_cluster_scrollbar
        prev_value = self._sim_cluster_prev_value
        total = self._sim_cluster_total
        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        self._agg_group_rows = {}
        self._head_by_member = {}
        _hc = _rss_colors()

        for ci, cl in enumerate(clusters):
            head_key = "__sim_head__{}".format(ci)
            head_title = cl["title"] or "(无标题)"
            members = cl["items"]

            group_item = QtWidgets.QListWidgetItem()
            group_item.setData(QtCore.Qt.UserRole, head_key)
            group_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            lbl_head = _HeadRow()
            lbl_head.setToolTip(
                "单击标题=预览该分组最相关条目\n双击=默认打开一个来源\n单击来源徽标=展开查看全部相似条目")
            lbl_head.setText(head_title)
            lbl_head.set_count("{} 条".format(len(members)))
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
                lambda _=False, cl=cl: self._sim_head_preview(cl))
            lbl_head.badgeClicked.connect(
                lambda _=False, key=head_key: self._toggle_sim_group(key))
            lbl_head.headDoubleClicked.connect(
                lambda _=False, cl=cl: self._sim_head_open(cl))
            lbl_head.checkboxToggled.connect(
                lambda checked, key=head_key: self._on_sim_head_checkbox_toggled(key, checked))
            self.item_list.addItem(group_item)
            self.item_list.setItemWidget(group_item, lbl_head)
            self._node_item_by_head[head_key] = group_item
            self._head_buttons[head_key] = lbl_head
            self._group_children[head_key] = []

            for it in members:
                row_widget, title_btn, chk = _make_item_row(
                    self.item_list, it, None, show_thumbnail=self._show_thumbnails,
                    checked=it["hash"] in self._selected_hashes)
                title_btn.clicked.connect(
                    lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
                chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))
                chk.toggled.connect(
                    lambda _checked, key=head_key: self._sync_head_checkbox_state(key))
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
                self.item_list.setRowHidden(self.item_list.row(citem), True)
                self._group_children[head_key].append(citem)
            self._sync_head_checkbox_state(head_key)

        self.lb_page.setText("第 1 页")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        self.lb_total.setText("相似性聚合 ◈ {} 个分组 · 共 {} 条".format(len(clusters), total))
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        if prev_value is not None and scrollbar is not None:
            scrollbar.setValue(min(prev_value, scrollbar.maximum()))

    def _sim_head_preview(self, cluster):
        """单击相似性分组头标题：预览该分组最相关(最近)的一条。"""
        members = cluster.get("items") or []
        if not members:
            return
        it = members[0]
        self.owner.store.mark_read(it["hash"])
        self._update_read_appearance(it["hash"], True)
        self._show_preview_by_hash(it["hash"], it["link"])

    def _sim_head_open(self, cluster):
        """双击相似性分组头：默认找一个来源并在系统浏览器打开。"""
        members = cluster.get("items") or []
        if not members:
            return
        it = members[0]
        link = it["link"]
        webbrowser.open(link)
        if it["hash"]:
            self.owner.store.mark_read(it["hash"])
            self._update_read_appearance(it["hash"], True)

    def _toggle_sim_group(self, head_key):
        group_item = self._group_children.get(head_key)
        if group_item is None:
            return
        hidden = self.item_list.isRowHidden(self.item_list.row(group_item[0]))
        for citem in group_item:
            self.item_list.setRowHidden(self.item_list.row(citem), not hidden)
        btn = self._head_buttons.get(head_key)
        if btn is not None:
            txt = btn.text()
            txt = txt.lstrip("▸ ▾ ▹ ▿ ")
            if hidden:
                btn.setText("▾ " + txt)
            else:
                btn.setText("▸ " + txt)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def _on_sim_head_checkbox_toggled(self, head_key, checked):
        members = self._group_children.get(head_key, [])
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
