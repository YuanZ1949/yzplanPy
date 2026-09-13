"""rss_store slice: feed auto-discovery mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from .store_conn import RssStoreBase


class DiscoverMixin(RssStoreBase):
    # ── Feed 自动发现 ─────────────────────────────────────────
    def discover_feed(self, url):
        import requests

        class FeedLinkParser:
            def __init__(self):
                self.feeds = []

            def feed(self, html):
                import re
                for m in re.finditer(r'<link[^>]+>', html, re.IGNORECASE):
                    tag = m.group(0)
                    attrs = {}
                    for am in re.finditer(r'(\w+)=["\']([^"\']+)["\']', tag):
                        attrs[am.group(1).lower()] = am.group(2)
                    rel = attrs.get("rel", "")
                    type_ = attrs.get("type", "")
                    href = attrs.get("href", "")
                    if "alternate" in rel and ("rss" in type_ or "atom" in type_ or "xml" in type_):
                        self.feeds.append({"type": type_, "href": href, "title": attrs.get("title", "")})

        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 YZplan"})
            resp.raise_for_status()
            parser = FeedLinkParser()
            parser.feed(resp.text)
            return parser.feeds
        except Exception:
            return []