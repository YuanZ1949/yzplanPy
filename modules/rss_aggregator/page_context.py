"""RSS 页面：右键菜单/OPML/分类关键词规则管理。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_e import _CategoryDialog, _FilterRuleDialog, _KeywordDialog
from .page_preview import _RssPageWidget
from .text_utils import _rss_colors
from ..rss_store import export_opml_file, import_opml_file

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _show_context_menu(self, pos):
        item = self.item_list.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)

        act_open = menu.addAction("打开链接")
        act_preview = menu.addAction("预览详情")
        act_copy = menu.addAction("复制链接")
        act_share = menu.addAction("分享到剪贴板")
        menu.addSeparator()
        act_read = menu.addAction("标记已读")
        act_unread = menu.addAction("标记未读")
        menu.addSeparator()
        act_fav = menu.addAction("收藏/取消收藏")
        menu.addSeparator()

        categories = self.owner.store.get_categories()
        if categories:
            cat_menu = menu.addMenu("添加到分类")
            for cat in categories:
                act = cat_menu.addAction(f"{cat['name']}")
                act.setData(cat["id"])

        action = menu.exec_(self.item_list.mapToGlobal(pos))
        if not action:
            return

        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)

        if action == act_open:
            if link:
                webbrowser.open(link)
        elif action == act_preview:
            self._show_preview(item)
        elif action == act_copy:
            if link:
                QtWidgets.QApplication.clipboard().setText(link)
        elif action == act_share:
            text = self.owner.store.share_item(h)
            if text:
                QtWidgets.QApplication.clipboard().setText(text)
                self.lb_status.setText("已复制到剪贴板")
        elif action == act_read:
            self.owner.store.mark_read(h)
            self._load_items()
        elif action == act_unread:
            self.owner.store.mark_unread(h)
            self._load_items()
        elif action == act_fav:
            self.owner.store.toggle_favorite(h)
            self._load_items()
        elif hasattr(action, "data") and action.data():
            cat_id = action.data()
            self.owner.store.set_item_category(h, cat_id)

    def _export_opml(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出 OPML", "subscriptions.opml", "OPML Files (*.opml)")
        if path:
            try:
                export_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导出到 {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _import_opml(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入 OPML", "", "OPML Files (*.opml);;All Files (*)")
        if path:
            try:
                count = import_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导入 {count} 个订阅源")
                self._load_feeds()
                self._load_tag_filter()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _save_proxy(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner._proxy = proxy

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.context.config.set("rss.cleanup_days", days)
        self.owner.store.cleanup_old(days)
        self._load_items()
        QtWidgets.QMessageBox.information(self, "完成", f"已清理 {days} 天前的数据")

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            item = QtWidgets.QListWidgetItem(f"{kw['keyword']} ({kw['color']})")
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if item:
            kid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_keyword(kid)
            self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for rule in self.owner.store.get_filter_rules():
            status = "✓" if rule["enabled"] else "✗"
            text = f"{status} {rule['name']}: {rule['field']} {rule['operator']} '{rule['value']}' → {rule['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, rule["id"])
            item.setData(QtCore.Qt.UserRole + 1, rule["enabled"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_filter_rule(rid)
            self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            enabled = item.data(QtCore.Qt.UserRole + 1)
            self.owner.store.update_filter_rule(rid, enabled=not enabled)
            self._load_rules()

    def _load_categories(self):
        self.category_list.clear()
        for cat in self.owner.store.get_categories():
            item = QtWidgets.QListWidgetItem(f"{cat['name']} ({cat['color']})")
            item.setData(QtCore.Qt.UserRole, cat["id"])
            item.setData(QtCore.Qt.UserRole + 1, cat)
            self.category_list.addItem(item)

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if item:
            cat = item.data(QtCore.Qt.UserRole + 1)
            dlg = _CategoryDialog(self.owner, self, category=cat)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if item:
            cid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_category(cid)
            self._load_categories()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(20):
            text = f"[{h['read_at']}] {h['title']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        stats = self.owner.store.get_feed_stats()
        total_items = self.owner.store.get_item_count()
        total_unread = self.owner.store.get_unread_count()
        lines = [f"总条目: {total_items}", f"未读: {total_unread}", ""]
        for s in stats:
            lines.append(f"{s['name']}: {s['total']}条 (未读:{s['unread']})")
        self.lb_stats.setText("\n".join(lines))
