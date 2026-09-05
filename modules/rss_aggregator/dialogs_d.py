"""RSS 对话框 D：设置对话框（后半）。"""

import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .dialogs_c import _SettingsDialog
from .dialogs_e import _CategoryDialog, _FilterRuleDialog, _KeywordDialog

logger = logging.getLogger("rss_aggregator")

class _SettingsDialog(_SettingsDialog):

    def _save_settings(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner.set_proxy(proxy)
        self.owner.context.config.set("rss.cleanup_days", self.spin_cleanup_days.value())
        self.accept()

    def _apply_dialog_theme(self):
        # 与其他页面/对话框一致：不覆盖全局 QFluentWidgets 主题/QSS，
        # 让 QGroupBox/QSpinBox/QLineEdit 跟应用主题渲染；不使用壁纸，保持普通面板风格。
        self.setStyleSheet("")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.store.cleanup_old(days)
        self.owner.context.config.set("rss.cleanup_days", days)
        QtWidgets.QMessageBox.information(self, "清理", f"已清理 {days} 天前的数据")

    def _load_categories(self):
        self.category_list.clear()
        for c in self.owner.store.get_categories():
            self.category_list.addItem(f"{c['name']} ({c['color']})")

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            dlg = _CategoryDialog(self.owner, cats[idx], self)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            self.owner.store.remove_category(cats[idx]["id"])
            self._load_categories()

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            text = kw["keyword"]
            if kw.get("notify"):
                text += " 🔔"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if not item:
            return
        kid = item.data(QtCore.Qt.UserRole)
        if kid is None:
            return
        self.owner.store.remove_keyword(kid)
        self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for r in self.owner.store.get_filter_rules():
            status = "✓" if r.get("enabled") else "✗"
            text = f"{status} {r['name']}: {r['field']} {r['operator']} {r['value']} → {r['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, r["id"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_filter_rule(rid)
        self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        rules = self.owner.store.get_filter_rules()
        for r in rules:
            if r["id"] == rid:
                self.owner.store.update_filter_rule(rid, enabled=not r.get("enabled", True))
                break
        self._load_rules()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(limit=50):
            item = QtWidgets.QListWidgetItem(f"{h['title'][:50]} ({h['read_at']})")
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        feed_stats = self.owner.store.get_feed_stats()
        total = sum(s.get("total", 0) for s in feed_stats)
        unread = sum(s.get("unread", 0) for s in feed_stats)
        read = total - unread
        fav_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM favorites").fetchone()
            fav_count = row["cnt"] if row else 0
        today_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM items WHERE date(published) = date('now','localtime')"
            ).fetchone()
            today_count = row["cnt"] if row else 0
        self.lb_stats.setText(
            f"总条目: {total} | 已读: {read} | 未读: {unread} | 收藏: {fav_count} | 今日新增: {today_count}"
        )
