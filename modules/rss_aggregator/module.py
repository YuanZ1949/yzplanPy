"""rss_aggregator 模块入口：MODULE_INFO 与 Module。"""

import json
import logging
import os
import sys
import threading

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.perf import mark_webengine_alive, timed

from ..base import ModuleBase
from ..rss_store import RssStore
from .fetchers import _Fetcher, _HashScanner
from .home import _RssHomeWidget
from .page_context import _RssPageWidget
from .preview import _PREVIEW_KEEP
from .utils import _FaviconWorker

logger = logging.getLogger("rss_aggregator")

MODULE_INFO = {
    "id": "rss_aggregator",
    "name": "RSS 聚合",
    "description": "多来源聚合、去重与来源标签标注",
}


class Module(ModuleBase):
    MODULE_ID = "rss_aggregator"
    MODULE_NAME = "RSS 聚合"
    MODULE_DESCRIPTION = "多来源聚合、去重与来源标签标注"

    def __init__(self, context):
        super().__init__(context)
        from core.constants import DB_PATH
        self.store = RssStore(DB_PATH)
        self._timer = None
        self._thread = None
        self._scan_thread = None
        self._scan_running = False
        self._widgets = []
        self._notification_callback = None
        self._proxy = context.config.get("rss.proxy", "")
        self._retry_count = 3
        self._retry_delay = 5

    def start(self):
        if self._running:
            return
        super().start()
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60 * 1000)
        self._auto_refresh()
        if self.context.config.get("rss.auto_cleanup", False):
            self.store.cleanup_old(self.context.config.get("rss.cleanup_days", 30))
        if self.context.config.get("rss.auto_hash_scan", False):
            QtCore.QTimer.singleShot(3000, self.scan_hashes)
        logger.info("RSS模块已启动")

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        # 清理全局 WebEngine 预览引用，防止模块重载/重启时残留无效对象
        global _PREVIEW_KEEP
        _PREVIEW_KEEP["view"] = None
        _PREVIEW_KEEP["page"] = None
        _PREVIEW_KEEP["profile"] = None
        _PREVIEW_KEEP["render_process_alive"] = True
        try:
            from core.perf import mark_webengine_alive
            mark_webengine_alive(False)
        except Exception:
            pass
        super().stop()
        logger.info("RSS模块已停止")

    def trigger_preview(self, hash_, link):
        """触发指定条目的预览（通过 MCP inbox 调用）。"""
        try:
            for w in self._widgets:
                if hasattr(w, "_show_preview_by_hash"):
                    w._show_preview_by_hash(str(hash_), str(link or ""))
                    break
        except Exception as e:
            logger.debug("trigger_preview 失败: %s", e)

    def scan_hashes(self, limit=200):
        """后台启动磁链 hash 扫描（限速）。已在扫描则忽略。"""
        if self._scan_running or self._scan_thread is not None:
            return
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._scanner = _HashScanner(
            self.store, self._proxy,
            retry_count=self._retry_count, retry_delay=self._retry_delay,
            rate_limit_ms=self.context.config.get("rss.scan_rate_limit_ms", 1000),
        )
        self._scanner.done.connect(self._on_scan_done)
        self._scan_running = True
        self._scan_thread = threading.Thread(target=self._scanner.run, kwargs={"limit": limit, "magnet_only": True}, daemon=True)
        self._scan_thread.start()

    def _on_scan_done(self, scanned):
        self._scan_running = False
        self._scan_thread = None
        for w in list(self._widgets):
            try:
                w.on_hash_scan_done(scanned)
            except RuntimeError:
                self._forget_widget(w)

    def refresh_favicons(self):
        """后台抓取缺少 favicon 的订阅源图标。"""
        t = getattr(self, "_fav_thread", None)
        if t is not None and t.is_alive():
            return
        self._fav = _FaviconWorker(self.store, self._proxy)
        self._fav.done.connect(self._on_fav_done)
        self._fav_thread = threading.Thread(target=self._fav.run, daemon=True)
        self._fav_thread.start()

    def _on_fav_done(self):
        self._fav_thread = None
        for w in list(self._widgets):
            try:
                w.on_favicons_loaded()
            except RuntimeError:
                self._forget_widget(w)

    def set_notification_callback(self, callback):
        self._notification_callback = callback

    def set_proxy(self, proxy):
        self._proxy = proxy or ""
        logger.info("RSS代理已更新: %s", self._proxy or "无")

    def _auto_refresh(self):
        feeds = self.store.get_feeds_needing_refresh()
        if feeds and self._thread is None:
            logger.debug("自动刷新触发, %d个源需要更新", len(feeds))
            self._do_refresh(feeds)

    def refresh_now(self):
        feeds = [f for f in self.store.list_feeds() if f["enabled"]]
        if not feeds or self._thread is not None:
            return
        logger.info("手动刷新, %d个源", len(feeds))
        self._do_refresh(feeds)

    def _do_refresh(self, feeds):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        max_workers = self.context.config.get("rss.async_workers", 4)
        self._fetcher = _Fetcher(feeds, self.store, self._proxy, self._retry_count, self._retry_delay, max_workers)
        self._fetcher.finished.connect(self._on_refreshed)
        self._fetcher.item_added.connect(self._on_item_added)
        self._fetcher.feed_done.connect(self._on_feed_done)
        self._thread = threading.Thread(target=self._fetcher.run, daemon=True)
        self._thread.start()

    def _on_item_added(self, item_info):
        if self._notification_callback:
            self._notification_callback(item_info)

    def _on_feed_done(self, info):
        # 每源完成即通知所有页面实时刷新（侧边栏计数 + 列表）
        # 并刷新该订阅源所属的手动聚合快照
        feed_id = (info or {}).get("feed_id")
        try:
            self.refresh_aggs_for_feed(feed_id)
        except Exception as ex:
            logger.warning("feed done 刷新聚合失败: %s", ex)
        for w in list(self._widgets):
            try:
                w.on_feed_done(info)
            except RuntimeError:
                self._forget_widget(w)

    def refresh_aggs_for_feed(self, feed_id):
        """刷新包含该订阅源的所有手动聚合及其子聚合的快照（纯 SQL，无网络）。"""
        if not feed_id:
            return
        all_aggs = self.store.list_aggregations()
        # 1) 直接包含该 feed 的聚合
        affected = [a["id"] for a in all_aggs
                    if feed_id in json.loads(a.get("feed_ids") or "[]")]
        # 2) 父聚合被刷新 → 子聚合也需刷新
        affected += [a["id"] for a in all_aggs
                     if int(a.get("parent_id") or 0) in affected]
        affected = list(dict.fromkeys(affected))
        id_map = {a["id"]: a for a in all_aggs}
        for agg_id in affected:
            a = id_map.get(agg_id)
            if a is None:
                continue
            try:
                self.store.refresh_aggregation(agg_id)
            except Exception as ex:
                logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)

    def refresh_aggregation(self, agg_id):
        self.store.refresh_aggregation(agg_id)
        for w in list(self._widgets):
            try:
                w.on_feed_done({})
            except RuntimeError:
                self._forget_widget(w)

    def refresh_all_aggregations(self):
        for a in self.store.list_aggregations():
            try:
                self.store.refresh_aggregation(a["id"])
            except Exception as ex:
                logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)
        for w in list(self._widgets):
            try:
                w.on_feed_done({})
            except RuntimeError:
                self._forget_widget(w)

    def _on_refreshed(self, counts):
        self._thread = None
        for w in list(self._widgets):
            try:
                w.on_refreshed(counts)
            except RuntimeError:
                self._forget_widget(w)
        if self.context.config.get("rss.auto_hash_scan", False):
            self._maybe_auto_scan()

    def _maybe_auto_scan(self):
        if self._scan_running or self._scan_thread is not None:
            return
        if self.store.get_pending_hash_scans(1, magnet_only=True):
            self.scan_hashes(limit=self.context.config.get("rss.scan_limit", 200))

    def _forget_widget(self, w):
        for i, x in enumerate(self._widgets):
            if x is w:
                del self._widgets[i]
                return

    def create_home_widget(self, parent):
        w = _RssHomeWidget(self, parent)
        self._widgets.append(w)
        w.destroyed.connect(lambda *_: self._forget_widget(w))
        return w

    def create_page(self, parent):
        w = _RssPageWidget(self, parent)
        self._widgets.append(w)
        w.destroyed.connect(lambda *_: self._forget_widget(w))
        return w
