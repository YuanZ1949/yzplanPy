"""rss_store slice: keywords mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from core.perf import trace

from .store_conn import RssStoreBase, _default_keyword_hex


class KeywordsMixin(RssStoreBase):
    # ── 关键词 ────────────────────────────────────────────────
    def get_keywords(self):
        if self._keywords_cache is not None:
            return self._keywords_cache
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM keywords ORDER BY keyword").fetchall()
        self._keywords_cache = [dict(r) for r in rows]
        return self._keywords_cache

    def invalidate_keywords_cache(self):
        self._keywords_cache = None

    def add_keyword(self, keyword, color=None, notify=1):
        if color is None:
            color = _default_keyword_hex()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO keywords(keyword,color,notify) VALUES(?,?,?)",
                (keyword, color, notify),
            )
        self._keywords_cache = None

    def remove_keyword(self, keyword_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
        self._keywords_cache = None

    @trace()
    def check_keywords(self, title, description=""):
        keywords = self.get_keywords()
        matched = []
        text = f"{title} {description}".lower()
        for kw in keywords:
            if kw["keyword"].lower() in text:
                matched.append(kw)
        return matched