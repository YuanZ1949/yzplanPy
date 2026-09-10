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
from .text_utils import _cluster_by_similarity_gen

# 相似度阈值：标题相似度 >= 该值归入同一簇（0~1）
SIMILARITY_THRESHOLD = 0.55


class _SimilarityClusterWorker(QtCore.QThread):
    """后台相似度聚类线程。

    聚类是 O(n²) 纯 CPU 计算（数千条级别可能耗时数秒），放在后台线程执行，
    完成后 clustered(list, int) 经 Qt auto 队列回主线程渲染 —— 主线程全程
    不阻塞，仅承担渲染工作。
    """

    clustered = QtCore.Signal(list, int)  # clusters, total

    # 存活的聚类线程集合：防止 QThread 被垃圾回收时仍在运行（Qt 致命错误）
    _live = set()

    def __init__(self, members, threshold):
        super().__init__()
        self._members = members
        self._threshold = threshold
        type(self)._live.add(self)

    def run(self):
        try:
            gen = _cluster_by_similarity_gen(self._members, self._threshold)
            clusters = []
            while True:
                try:
                    next(gen)
                except StopIteration as e:
                    clusters = e.value
                    break
            self.clustered.emit(clusters, len(self._members))
        except Exception:
            logger.exception("相似度聚类线程异常")
            self.clustered.emit([], 0)

    def _cleanup(self):
        """线程结束后：等到底、从存活集合移除、延迟销毁。"""
        self.wait()
        type(self)._live.discard(self)
        self.deleteLater()


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _load_similarity_aggregation(self, agg_id):
        """相似性类型聚合：按标题相似度聚簇，每簇一行(默认折叠)，点开展开成员条目。

        聚类（CPU 密集）在后台 QThread 执行，主线程立即显示等待态；
        完成后经 clustered 信号回主线程分页渲染，切换视图时旧结果按令牌作废。
        """
        agg = self.owner.store.get_aggregation(agg_id)
        threshold = float((agg or {}).get("similarity_threshold") or SIMILARITY_THRESHOLD)
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = scrollbar.value() if scrollbar is not None else None
        # 复用磁链聚合的整组查询：返回 {torrent_hash: [items]}，非磁链条目落在 "" 组。
        grouped = self.owner.store.get_all_aggregation_torrent_items(agg_id)
        all_members = []
        for _th, items in grouped.items():
            all_members.extend(items)
        total = len(all_members)

        # 令牌：期间切换视图/重新加载时，在途聚类结果直接作废，不渲染过期簇
        self._sim_load_token = getattr(self, "_sim_load_token", 0) + 1
        token = self._sim_load_token

        # 等待态：聚类完成后 _render_agg_page 会改写这两处
        self.lb_page.setText("相似性聚类中…")
        self.lb_total.setText("")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

        worker = _SimilarityClusterWorker(all_members, threshold)
        worker.clustered.connect(
            lambda clusters, t, tok=token: self._on_sim_clusters_ready(clusters, t, tok))
        worker.finished.connect(worker._cleanup)
        worker.start()
        self._sim_thread = worker
        self._sim_cluster_total = total
        self._sim_cluster_scrollbar = scrollbar
        self._sim_cluster_prev_value = prev_value

    def _on_sim_clusters_ready(self, clusters, total, token):
        """聚类线程完成（主线程执行）：令牌匹配才渲染，否则丢弃过期结果。"""
        if token != getattr(self, "_sim_load_token", -1):
            return
        self._sim_cluster_total = total
        self._render_similarity_clusters(clusters)

    def _render_similarity_clusters(self, clusters):
        """把聚类结果缓存为分组 dicts，交给共享分页渲染器 _render_agg_page。"""
        scrollbar = self._sim_cluster_scrollbar
        prev_value = self._sim_cluster_prev_value
        total = self._sim_cluster_total
        self._agg_groups = []
        for ci, cl in enumerate(clusters):
            head_key = "__sim_head__{}".format(ci)
            members = cl["items"]
            self._agg_groups.append({
                "head_key": head_key,
                "title": cl["title"] or "(无标题)",
                "count_text": "{} 条".format(len(members)),
                "members": members,
                "head_tooltip": "单击标题=预览该分组最相关条目\n双击=默认打开一个来源\n单击来源徽标=展开查看全部相似条目",
                "head_data": head_key,
                "title_cb": lambda _=False, cl=cl: self._sim_head_preview(cl),
                "open_cb": lambda _=False, cl=cl: self._sim_head_open(cl),
                "toggle_cb": lambda _=False, key=head_key: self._toggle_sim_group(key),
                "checkbox_cb": lambda checked, key=head_key: self._on_sim_head_checkbox_toggled(key, checked),
            })
        self._agg_mode = True
        self._agg_page = 0
        self._agg_kind_label = "相似性聚合"
        self._agg_total_items = total
        self._render_agg_page(scrollbar=scrollbar, prev_value=prev_value)

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
        # 展开/折叠状态存全局集合，跨页保留
        if head_key in self._agg_expanded:
            self._agg_expanded.discard(head_key)
        else:
            self._agg_expanded.add(head_key)
        self._apply_head_expansion(head_key)
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
