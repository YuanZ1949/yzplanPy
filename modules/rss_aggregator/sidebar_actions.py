"""RSS 侧栏：事件与操作。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_a import _EditFeedDialog
from .dialogs_f import _AddAggregationDialog
from .sidebar_data import _RssSidebar
from .styles import _btn_primary_style, _sidebar_qss
from .text_utils import _qf, _rss_colors

class _RssSidebar(_RssSidebar):

    # ── 事件 ──────────────────────────────────────────────
    def _on_sort_changed(self, index):
        self._apply_sort(index)
        self.reload()

    def _on_selection_changed(self):
        self.page.on_sidebar_selection_changed()

    def _on_double_clicked(self, item):
        d = item.data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg":
            self.page._open_aggregation(d.get("agg_id"))

    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        d = item.data(QtCore.Qt.UserRole)
        if not d:
            return
        menu = QtWidgets.QMenu(self)
        kind = d.get("kind")
        if kind == "agg":
            act_refresh = menu.addAction("刷新聚合")
            act_refresh.triggered.connect(lambda: self.owner.refresh_aggregation(d["agg_id"]))
            act_edit = menu.addAction("编辑聚合")
            act_edit.triggered.connect(lambda: self._edit_aggregation(d["agg_id"]))
            act_del = menu.addAction("删除聚合")
            act_del.triggered.connect(lambda: self._remove_aggregation(d["agg_id"]))
        elif kind == "feed":
            act_edit = menu.addAction("编辑订阅")
            act_edit.triggered.connect(lambda: self._edit_feed(d["feed_id"]))
            act_toggle = menu.addAction("启用/停用")
            act_toggle.triggered.connect(lambda: self._toggle_feed(d["feed_id"]))
            act_del = menu.addAction("删除订阅")
            act_del.triggered.connect(lambda: self._remove_feed(d["feed_id"]))
        else:
            act = menu.addAction("刷新")
            act.triggered.connect(self.page._refresh)
        menu.exec(self.mapToGlobal(pos))

    # ── 操作 ──────────────────────────────────────────────
    def _add_feed(self):
        self.page._show_add_feed()

    def _add_aggregation(self):
        self.page._show_add_aggregation()

    def _edit_aggregation(self, agg_id):
        self.page._show_edit_aggregation(agg_id)

    def _remove_aggregation(self, agg_id):
        if not QtWidgets.QMessageBox.question(self, "删除聚合", "确定删除该聚合？") == QtWidgets.QMessageBox.Yes:
            return
        self.owner.store.remove_aggregation(agg_id)
        self.page._reload_sidebar()
        self.page.on_sidebar_selection_changed()

    def _edit_feed(self, feed_id):
        feed = self.owner.store.get_feed_by_id(feed_id)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self.page)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.page._reload_sidebar()
            self.page._load_items(preserve_scroll=True)

    def _toggle_feed(self, feed_id):
        feed = self.owner.store.get_feed_by_id(feed_id)
        if feed:
            self.owner.store.set_feed_enabled(feed_id, not feed["enabled"])
            self.page._reload_sidebar()

    def _remove_feed(self, feed_id):
        if not QtWidgets.QMessageBox.question(self, "删除订阅", "确定删除该订阅源？") == QtWidgets.QMessageBox.Yes:
            return
        self.owner.store.remove_feed(feed_id)
        self.page._reload_sidebar()
        self.page.on_sidebar_selection_changed()

    def _scan_magnet(self):
        self.owner.scan_hashes(limit=self.owner.context.config.get("rss.scan_limit", 200))

    def _refresh_icons(self):
        self.owner.refresh_favicons()

    def _refresh_all_aggs(self):
        self.owner.refresh_all_aggregations()

    def _on_refresh_toggle(self, key, checked):
        self._refresh_ops[key] = checked

    def _run_selected_refresh(self):
        selected = [k for k, v in self._refresh_ops.items() if v]
        if not selected:
            return
        # 先清除勾选（toggled(False) 会同步 _refresh_ops），再执行
        for act in self._refresh_actions.values():
            if act.isChecked():
                act.setChecked(False)
        self._run_refresh_ops(selected)

    def _refresh_all_now(self):
        self._run_refresh_ops(["feeds", "scan", "icons", "aggs"])

    def _run_refresh_ops(self, ops):
        for op in ops:
            try:
                if op == "feeds":
                    self.owner.refresh_now()
                elif op == "scan":
                    self.owner.scan_hashes(limit=self.owner.context.config.get("rss.scan_limit", 200))
                elif op == "icons":
                    self.owner.refresh_favicons()
                elif op == "aggs":
                    self.owner.refresh_all_aggregations()
            except Exception as ex:
                logger.warning("刷新操作 %s 失败: %s", op, ex)

