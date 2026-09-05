"""RSS 抓取器：_Fetcher 拉取线程、_HashScanner 磁链扫描。"""

import html
import json
import logging
import re
import threading

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.perf import timed

from ..rss_store import _hash, _is_magnet_or_torrent, extract_btih, fetch_feed, scrape_page

logger = logging.getLogger("rss_aggregator")

class _Fetcher(QtCore.QObject):
    finished = QtCore.Signal(list)
    item_added = QtCore.Signal(dict)
    feed_done = QtCore.Signal(dict)

    def __init__(self, feeds, store, proxy="", retry_count=3, retry_delay=5, max_workers=4):
        super().__init__()
        self.feeds = feeds
        self.store = store
        self.proxy = proxy
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.max_workers = max(1, int(max_workers) if max_workers else 4)
        self._lock = threading.RLock()

    def _final_tags(self, f):
        if f.get("tags"):
            return [t for t in f["tags"] if t]
        tags = self.store.get_feed_tags(f["id"])
        if tags:
            return tags
        return [f["tag"] or f["name"]]

    def _final_tag(self, f, e):
        if e.get("extra_tag"):
            return e["extra_tag"]
        return (self._final_tags(f) or [f["name"]])[0]

    def _process_feed(self, f):
        """抓取单个源并入库，返回结果 dict。在 worker 线程调用。"""
        from core.perf import timed
        try:
            with timed(f"rss.fetch.{f.get('name', 'feeds')}"):
                if f.get("feed_type") == "scrape":
                    opts = json.loads(f.get("scrape_options") or "{}")
                    rendered = bool(f.get("rendered"))
                    entries = scrape_page(
                        f["url"], opts,
                        proxy=self.proxy,
                        timeout=15,
                        custom_headers=json.loads(f.get("custom_headers", "{}")),
                        retry_count=self.retry_count,
                        retry_delay=self.retry_delay,
                        rendered=rendered,
                    )
                    etag = None
                    last_modified = None
                else:
                    logger.debug("开始抓取: %s (%s)", f["name"], f["url"])
                    entries, _feed_title, etag, last_modified = fetch_feed(
                        f["url"],
                        proxy=self.proxy,
                        custom_headers=json.loads(f.get("custom_headers", "{}")),
                        etag=f.get("etag") or None,
                        last_modified=f.get("last_modified") or None,
                        retry_count=self.retry_count,
                        retry_delay=self.retry_delay,
                    )
                    if not entries and etag:
                        logger.debug("304 无更新: %s", f["name"])
                        self.store.update_feed_refresh_time(f["id"])
                        return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": ""}

            entries = self.store.apply_filter_rules(entries)
            entries = [e for e in entries if not e.get("_skip")]
            for e in entries:
                e["_final_tag"] = self._final_tag(f, e)
            with self._lock:
                added = self.store.ingest(self._final_tags(f), entries, feed_id=f["id"])
            self.store.update_feed_refresh_time(f["id"])
            if etag is not None:
                self.store.update_feed(f["id"], etag=etag or "", last_modified=last_modified or "")
            self.store.clear_feed_error(f["id"])
            # 自动检测该源是否为磁力/种子源（返回结果里带 hash/磁链/种子）
            if any((e.get("torrent_hash") or extract_btih(e.get("link", "")))
                   for e in entries):
                self.store.set_feed_is_torrent(f["id"], 1)
            logger.info("抓取完成: %s — %d条, 新增%d条", f["name"], len(entries), added)
            for e in entries:
                if added > 0:
                    matched_kw = self.store.check_keywords(e.get("title", ""), e.get("description", ""))
                    if matched_kw:
                        self.item_added.emit(
                            {
                                "title": e.get("title", ""),
                                "link": e.get("link", ""),
                                "source": f["name"],
                                "keywords": [kw["keyword"] for kw in matched_kw],
                            }
                        )
            return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": len(entries), "added": added, "error": ""}
        except Exception as ex:
            logger.warning("抓取失败: %s — %s", f["name"], ex)
            self.store.set_feed_error(f["id"], str(ex))
            return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": str(ex)}

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        counts = []

        def work(f):
            r = self._process_feed(f)
            r = r or {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": ""}
            self.feed_done.emit(r)
            return (r.get("name", ""), r.get("tag", ""), r.get("total", 0), r.get("added", 0))

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            counts = list(ex.map(work, self.feeds))
        self.finished.emit(counts)


_TORRENT_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']*(?:magnet:|\.torrent|urn:btih:)[^"\']*)["\']', re.IGNORECASE)
_MAGNET_BARE_RE = re.compile(r'magnet:\?[^\s"\'<>]+', re.IGNORECASE)


class _HashScanner(QtCore.QObject):
    """后台、限速的磁链/种子 hash 解析器：抓取无 hash 条目的原文页检索磁力/种子链接并缓存。"""
    done = QtCore.Signal(int)

    def __init__(self, store, proxy="", retry_count=1, retry_delay=2, rate_limit_ms=1000):
        super().__init__()
        self.store = store
        self.proxy = proxy
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.rate_limit_ms = max(50, rate_limit_ms or 1000)

    def _fetch_links(self, url):
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        try:
            resp = requests.get(url, timeout=12, headers=headers, proxies=proxies, verify=False)
            resp.raise_for_status()
            html = resp.text or ""
        except Exception:
            return []
        found = []
        for m in _TORRENT_HREF_RE.finditer(html):
            u = m.group(1).strip()
            if u and u not in found:
                found.append(u)
        for m in _MAGNET_BARE_RE.finditer(html):
            u = m.group(0).strip()
            if u and u not in found:
                found.append(u)
        # 补齐相对 .torrent 链接
        from urllib.parse import urljoin
        resolved = []
        for u in found:
            if u.startswith("/") and not (u.startswith("magnet:")):
                u = urljoin(url, u)
            resolved.append(u)
        return resolved

    def run(self, limit=200, magnet_only=True):
        import time
        pending = self.store.get_pending_hash_scans(limit, magnet_only=magnet_only)
        if not pending:
            self.done.emit(0)
            return
        self.store.mark_hash_scan([p["hash"] for p in pending], 1)
        scanned = 0
        for idx, p in enumerate(pending):
            if idx > 0:
                time.sleep(self.rate_limit_ms / 1000.0)
            link = p.get("link") or ""
            if _is_magnet_or_torrent(link):
                # 链接自带磁力/种子：直接并入（hash 由 record 提取）
                links = [link] if link else []
            else:
                links = self._fetch_links(link)
            if links:
                self.store.record_item_torrent_links(p["hash"], links)
                scanned += 1
            else:
                self.store.mark_hash_scan([p["hash"]], 3)
        self.done.emit(scanned)
