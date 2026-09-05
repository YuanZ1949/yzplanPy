"""modules/rss_store slice: feed fetching / page scraping.

Spliced from modules/rss_store.py by T13 codebase-reorg.
"""
import logging
from core.perf import trace
from .pure import _detect_encoding, _extract_image, extract_btih
from .scrapers_selector import scrape_html

logger = logging.getLogger("rss_store")


def scrape_page(url, options, proxy="", timeout=15, custom_headers=None, retry_count=3, retry_delay=5, rendered=False):
    """抓取网页并提取条目。rendered 时用 WebEngine 渲染后提取（需在 Qt 主线程）。"""
    import requests
    import time

    if rendered:
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception as ex:
            raise Exception(f"WebEngine 不可用: {ex}")
        view = QWebEngineView()
        view.resize(1280, 4096)
        loaded = [False]
        loop = QtCore.QEventLoop()

        def _on_loaded(_ok):
            loaded[0] = True
            loop.quit()

        view.loadFinished.connect(_on_loaded)
        view.load(QtCore.QUrl(url))
        QtCore.QTimer.singleShot(timeout * 1000 + 8000, loop.quit)
        loop.exec()
        if not loaded[0]:
            view.deleteLater()
            raise Exception("页面渲染超时")
        result = {}
        loop2 = QtCore.QEventLoop()

        def _got_html(h):
            result["html"] = h or ""
            loop2.quit()

        view.page().toHtml(_got_html)
        QtCore.QTimer.singleShot(timeout * 1000 + 8000, loop2.quit)
        loop2.exec()
        html = result.get("html", "")
        view.deleteLater()
        return scrape_html(html, options, url)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
    if custom_headers:
        headers.update(custom_headers)
    proxies = {"http": proxy, "https": proxy} if proxy else None
    last_error = None
    for attempt in range(max(1, retry_count)):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers, proxies=proxies)
            resp.raise_for_status()
            encoding = _detect_encoding(resp.content)
            try:
                text = resp.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                text = resp.content.decode("utf-8", errors="replace")
            return scrape_html(text, options, url)
        except Exception as e:
            last_error = str(e)
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
    raise Exception(f"Failed after {retry_count} attempts: {last_error}")


@trace()
def fetch_feed(url, timeout=15, proxy=None, custom_headers=None, etag=None, last_modified=None, retry_count=3, retry_delay=5):
    import feedparser
    import requests
    import time

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
    if custom_headers:
        headers.update(custom_headers)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    proxies = {"http": proxy, "https": proxy} if proxy else None
    last_error = None

    for attempt in range(retry_count):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers, proxies=proxies)
            if resp.status_code == 304:
                logger.debug("304 Not Modified: %s", url)
                return [], "", etag, last_modified
            resp.raise_for_status()

            new_etag = resp.headers.get("ETag")
            new_last_modified = resp.headers.get("Last-Modified")

            encoding = _detect_encoding(resp.content)
            try:
                text = resp.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                text = resp.content.decode("utf-8", errors="replace")

            data = feedparser.parse(text)
            entries = []
            for e in data.entries:
                desc = ""
                if hasattr(e, "summary"):
                    desc = e.summary
                elif hasattr(e, "content"):
                    desc = e.content[0].get("value", "")
                image = _extract_image(desc, e.get("link", ""))
                # 收集磁力/种子链接：优先 enclosure（RSS 附带磁链最常见），再 link，再描述
                links_for_hash = []
                try:
                    for enc in (e.get("enclosures") or []):
                        u = enc.get("href") or enc.get("url") or ""
                        if u:
                            links_for_hash.append(u)
                    links_for_hash.append(e.get("link", ""))
                    if desc:
                        links_for_hash.append(desc)
                except Exception:
                    pass
                torrent_hash = ""
                for cand in links_for_hash:
                    torrent_hash = extract_btih(cand or "")
                    if torrent_hash:
                        break
                entries.append(
                    {
                        "title": e.get("title", ""),
                        "link": e.get("link", ""),
                        "published": e.get("published", ""),
                        "description": desc,
                        "image_url": image,
                        "torrent_hash": torrent_hash,
                    }
                )
            logger.debug("抓取成功: %s, %d条目", url, len(entries))
            return entries, data.feed.get("title", ""), new_etag, new_last_modified

        except Exception as e:
            last_error = str(e)
            logger.warning("抓取失败 (尝试%d/%d): %s — %s", attempt + 1, retry_count, url, e)
            if attempt < retry_count - 1:
                time.sleep(retry_delay)

    raise Exception(f"Failed after {retry_count} attempts: {last_error}")
