"""RSS 页面：刷新回调/通知/源管理。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .page_settings_build import _RssPageWidget
from .dialogs_b import _AddFeedDialog

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _schedule_reload(self):
        """风暴合并：后台刷新每源完成/聚合广播密集触发全量重建时，
        合并为一次最终刷新（250ms 去抖），避免主线程被行布局计算拖死。"""
        if getattr(self, "_reload_timer", None) is None:
            self._reload_timer = QtCore.QTimer(self)
            self._reload_timer.setSingleShot(True)
            self._reload_timer.setInterval(250)
            self._reload_timer.timeout.connect(self._do_reload)
        self._reload_timer.start()

    def _do_reload(self):
        self._load_items(preserve_scroll=True)
        self._reload_sidebar()
        self._refresh_header_summary()

    def on_refreshed(self, counts):
        if counts:
            parts = ["{}: {}/{}".format(n, added, total) for n, tag, total, added in counts]
            self.lb_status.setText("刷新完成 — " + ", ".join(parts))
            self._notify("刷新完成", " · ".join(parts))
        else:
            self.lb_status.setText("刷新完成")
            self._notify("刷新完成", "没有新内容")
        self._schedule_reload()

    def on_feed_done(self, info):
        self._schedule_reload()

    def _refresh_header_summary(self):
        """刷新头部概览：订阅 / 聚合 / 未读 / 最近更新时间。"""
        if not hasattr(self, "lb_summary"):
            return
        try:
            data = self.owner.store.list_sidebar()
            feeds = len([f for f in data.get("feeds", []) if f.get("enabled")])
            aggs = len(data.get("aggregations", []))
            parts = [f"订阅 {feeds}", f"聚合 {aggs}"]
            unread = 0
            for f in data.get("feeds", []):
                unread += int(f.get("unread") or 0)
            if unread:
                parts.insert(1, f"未读 {unread}")
            last = (data.get("aggregations") or [{}])[0].get("last_refreshed") or ""
            if last:
                self.lb_summary.setText(" · ".join(parts + [f"更新 {str(last)[:16]}"]))
            else:
                self.lb_summary.setText(" · ".join(parts))
        except Exception:
            self.lb_summary.setText("")

    def _notify(self, title, content="", level="success"):
        """弹出轻量 InfoBar 提示；仅在页面可见时弹，失败静默。"""
        try:
            if not (self.isVisible() and self.window().isVisible()):
                return
            from qfluentwidgets import InfoBar, InfoBarPosition
            getattr(InfoBar, level)(title=title, content=content, parent=self.window(),
                                    position=InfoBarPosition.TOP_RIGHT, duration=3000)
        except Exception:
            pass

    def _reload_sidebar(self):
        if hasattr(self, "_sidebar"):
            self._sidebar.reload()

    def on_sidebar_selection_changed(self):
        cfg = self.owner.context.config
        sel = self._sidebar.current_filter()
        kind = None
        d = self._sidebar.current_data() or {}
        kind = (d or {}).get("kind")
        cfg.set("rss.sidebar.kind", kind)
        cfg.set("rss.sidebar.feed_id", (d or {}).get("feed_id") if kind == "feed" else None)
        cfg.set("rss.sidebar.agg_id", (d or {}).get("agg_id") if kind == "agg" else None)
        cfg.set("rss.sidebar.keyword", None)
        cfg.set("rss.sidebar.torrent_hash", None)
        self._current_page = 0
        self._load_items()

    def on_hash_scan_done(self, scanned):
        self._schedule_reload()

    def on_favicons_loaded(self):
        self._reload_sidebar()

    def _show_add_dialog(self):
        dlg = _AddFeedDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()
            self._load_tag_filter()

    def _remove_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_feed(fid)
        self._load_feeds()
        self._load_tag_filter()

    def _toggle_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        enabled = item.data(QtCore.Qt.UserRole + 1)
        self.owner.store.set_feed_enabled(fid, not enabled)
        self._load_feeds()
