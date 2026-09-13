"""rss_store slice: item / read / history / favorites mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from datetime import datetime

from core.perf import trace

from .pure import _hash, _normalize_published, extract_btih, normalize_btih
from .store_conn import RssStoreBase, logger


class ItemsMixin(RssStoreBase):
    # ── Item 管理 ──────────────────────────────────────────────
    def ingest(self, tag, entries, feed_id=None):
        if isinstance(tag, str):
            tags = [tag]
        else:
            tags = list(tag or [])
        tags = [t for t in tags if t]
        added = 0
        with self._conn() as conn:
            for e in entries:
                title = e.get("title") or (e.get("link") or "")
                link = e.get("link") or ""
                published = e.get("published", "")
                description = e.get("description", "")
                image_url = e.get("image_url", "")
                h = _hash(title, link)
                # 优先取条目显式提供的 hash（来自 enclosure/磁链解析），否则从 link/描述 提取
                provided = (e.get("torrent_hash") or "").strip() if isinstance(e, dict) else ""
                if provided:
                    torrent_hash = normalize_btih(provided) or extract_btih(provided)
                else:
                    torrent_hash = extract_btih(link) or extract_btih(description)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO items(hash,title,link,published,description,image_url,torrent_hash) VALUES(?,?,?,?,?,?,?)",
                    (h, title, link, _normalize_published(published), description, image_url, torrent_hash),
                )
                if cur.rowcount and torrent_hash:
                    conn.execute("UPDATE items SET hash_scan_state=2 WHERE hash=?", (h,))
                elif not cur.rowcount and torrent_hash:
                    # 已存在但缺 hash：用本次带 hash 的条目回填（兼容修复既有数据）
                    cur2 = conn.execute(
                        "UPDATE items SET torrent_hash=?, hash_scan_state=2 WHERE hash=? AND (torrent_hash='' OR torrent_hash IS NULL)",
                        (torrent_hash, h),
                    )
                if cur.rowcount:
                    added += 1
                for t in tags:
                    conn.execute(
                        "INSERT OR IGNORE INTO item_sources(hash,tag) VALUES(?,?)",
                        (h, t),
                    )
                if feed_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO item_feeds(hash,feed_id) VALUES(?,?)",
                        (h, feed_id),
                    )
        if added:
            logger.debug("入库完成: 标签=%s, 新增=%d", tag, added)
            self._tags_cache = None
        return added

    @trace()
    def list_tags(self):
        if self._tags_cache is not None:
            return self._tags_cache
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT tag FROM item_sources ORDER BY tag"
            ).fetchall()
        self._tags_cache = [r["tag"] for r in rows]
        return self._tags_cache

    def invalidate_tags_cache(self):
        self._tags_cache = None

    @trace()
    def get_item(self, item_hash):
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                       GROUP_CONCAT(s.tag, ' | ') AS tags,
                       CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                       CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                FROM items i
                LEFT JOIN item_sources s ON i.hash = s.hash
                LEFT JOIN item_read r ON i.hash = r.hash
                LEFT JOIN favorites f ON i.hash = f.hash
                WHERE i.hash = ?
                GROUP BY i.hash
                """,
                (item_hash,),
            ).fetchone()
        return dict(row) if row else None

    def get_item_count(self):
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM items").fetchone()
        return row["cnt"] if row else 0

    def get_all_hashes(self, limit=None):
        with self._conn() as conn:
            if limit:
                rows = conn.execute(
                    "SELECT hash FROM items ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT hash FROM items ORDER BY id DESC").fetchall()
        return [r["hash"] for r in rows]

    # ── 已读管理 ──────────────────────────────────────────────
    def is_read(self, item_hash):
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM item_read WHERE hash=?", (item_hash,)).fetchone()
        return row is not None

    def mark_read(self, item_hash):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO item_read(hash) VALUES(?)", (item_hash,))
            conn.execute(
                "INSERT OR REPLACE INTO read_history(hash, read_at) VALUES(?, datetime('now','localtime'))",
                (item_hash,),
            )

    def mark_unread(self, item_hash):
        with self._conn() as conn:
            conn.execute("DELETE FROM item_read WHERE hash=?", (item_hash,))

    def mark_all_read(self, tag_filter=None):
        with self._conn() as conn:
            if tag_filter:
                rows = conn.execute(
                    "SELECT hash FROM item_sources WHERE tag=?", (tag_filter,)
                ).fetchall()
                hashes = [r["hash"] for r in rows]
            else:
                rows = conn.execute("SELECT hash FROM items").fetchall()
                hashes = [r["hash"] for r in rows]
            conn.executemany("INSERT OR IGNORE INTO item_read(hash) VALUES(?)", [(h,) for h in hashes])
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.executemany(
                "INSERT OR REPLACE INTO read_history(hash, read_at) VALUES(?,?)",
                [(h, now) for h in hashes],
            )

    def batch_mark_read(self, hashes):
        with self._conn() as conn:
            conn.executemany("INSERT OR IGNORE INTO item_read(hash) VALUES(?)", [(h,) for h in hashes])
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.executemany(
                "INSERT OR REPLACE INTO read_history(hash, read_at) VALUES(?,?)",
                [(h, now) for h in hashes],
            )

    def batch_mark_unread(self, hashes):
        with self._conn() as conn:
            conn.executemany("DELETE FROM item_read WHERE hash=?", [(h,) for h in hashes])

    def batch_delete(self, hashes):
        with self._conn() as conn:
            for h in hashes:
                conn.execute("DELETE FROM items WHERE hash=?", (h,))
                conn.execute("DELETE FROM item_sources WHERE hash=?", (h,))
                conn.execute("DELETE FROM item_read WHERE hash=?", (h,))
                conn.execute("DELETE FROM read_history WHERE hash=?", (h,))
                conn.execute("DELETE FROM favorites WHERE hash=?", (h,))
                conn.execute("DELETE FROM item_categories WHERE hash=?", (h,))
                # D18: 级联清理其余关联表，避免删除条目后残留孤儿关联
                conn.execute("DELETE FROM item_feeds WHERE hash=?", (h,))
                conn.execute("DELETE FROM aggregation_items WHERE hash=?", (h,))
                conn.execute("DELETE FROM item_torrent_links WHERE hash=?", (h,))
                conn.execute("DELETE FROM item_related WHERE hash1=? OR hash2=?", (h, h))

    def get_unread_count(self):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM items WHERE hash NOT IN (SELECT hash FROM item_read)"
            ).fetchone()
        return row["cnt"] if row else 0

    # ── 阅读历史 ──────────────────────────────────────────────
    def get_read_history(self, limit=100):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT i.hash, i.title, i.link, i.published, rh.read_at
                FROM read_history rh
                INNER JOIN items i ON rh.hash = i.hash
                ORDER BY rh.read_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 收藏 ──────────────────────────────────────────────────
    def toggle_favorite(self, item_hash):
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM favorites WHERE hash=?", (item_hash,)).fetchone()
            if row:
                conn.execute("DELETE FROM favorites WHERE hash=?", (item_hash,))
                return False
            else:
                conn.execute("INSERT OR IGNORE INTO favorites(hash) VALUES(?)", (item_hash,))
                return True

    def is_favorite(self, item_hash):
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM favorites WHERE hash=?", (item_hash,)).fetchone()
        return row is not None

    def set_favorite_note(self, item_hash, note):
        with self._conn() as conn:
            conn.execute("UPDATE favorites SET note=? WHERE hash=?", (note, item_hash))