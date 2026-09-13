"""rss_store slice: stats mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from .store_conn import RssStoreBase


class StatsMixin(RssStoreBase):
    # ── 统计 ──────────────────────────────────────────────────
    def get_feed_stats(self):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT f.name, f.tag, f.enabled,
                       COUNT(DISTINCT s.hash) as total,
                       COUNT(DISTINCT CASE WHEN r.hash IS NULL THEN s.hash END) as unread
                FROM feeds f
                LEFT JOIN item_sources s ON f.tag = s.tag
                LEFT JOIN item_read r ON s.hash = r.hash
                GROUP BY f.id
                ORDER BY f.name
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self):
        """按订阅源统计条目总数与已读数（供 mcp_server 等外部层复用）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT f.id, f.name, COUNT(i.hash) AS total, "
                "SUM(CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END) AS read_count "
                "FROM feeds f LEFT JOIN item_feeds if2 ON f.id=if2.feed_id "
                "LEFT JOIN items i ON if2.hash=i.hash "
                "LEFT JOIN item_read r ON i.hash=r.hash "
                "GROUP BY f.id ORDER BY f.name").fetchall()
        return [dict(r) for r in rows]