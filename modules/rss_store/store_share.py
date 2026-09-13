"""rss_store slice: share / related-items mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from .store_conn import RssStoreBase


class ShareMixin(RssStoreBase):
    # ── 分享 ──────────────────────────────────────────────────
    def share_item(self, item_hash):
        item = self.get_item(item_hash)
        if not item:
            return ""
        text = f"{item['title']}\n{item['link']}"
        if item.get("tags"):
            text += f"\n来源: {item['tags']}"
        return text

    # ── 相似条目 ──────────────────────────────────────────────
    def add_related(self, hash1, hash2, similarity=0.0):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO item_related(hash1,hash2,similarity) VALUES(?,?,?)",
                (hash1, hash2, similarity),
            )

    def get_related(self, item_hash, limit=10):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT i.hash, i.title, i.link, ir.similarity
                FROM item_related ir
                INNER JOIN items i ON (i.hash = ir.hash2 AND ir.hash1 = ?) OR (i.hash = ir.hash1 AND ir.hash2 = ?)
                WHERE i.hash != ?
                ORDER BY ir.similarity DESC
                LIMIT ?
                """,
                (item_hash, item_hash, item_hash, limit),
            ).fetchall()
        return [dict(r) for r in rows]