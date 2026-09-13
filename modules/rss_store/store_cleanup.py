"""rss_store slice: cleanup mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from datetime import datetime, timedelta

from .store_conn import RssStoreBase


class CleanupMixin(RssStoreBase):
    # ── 清理 ──────────────────────────────────────────────────
    def cleanup_old(self, days=30):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM items WHERE published < ? AND hash NOT IN (SELECT hash FROM favorites)",
                (cutoff,),
            )
            conn.execute("DELETE FROM item_sources WHERE hash NOT IN (SELECT hash FROM items)")
            conn.execute("DELETE FROM item_read WHERE hash NOT IN (SELECT hash FROM items)")
            conn.execute("DELETE FROM read_history WHERE hash NOT IN (SELECT hash FROM items)")

    def cleanup_old_by_date(self, days=30):
        """按 YYYY-MM-DD 日期截断清理旧条目（保留收藏），返回 (删除数, 截断日期)。"""
        cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM items WHERE hash NOT IN (SELECT hash FROM favorites) AND published < ?",
                (cutoff,))
            deleted = cur.rowcount
        return deleted, cutoff