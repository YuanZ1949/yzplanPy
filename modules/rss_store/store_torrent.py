"""rss_store slice: torrent links / hash scan mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
import json

from .pure import extract_btih
from .store_conn import RssStoreBase


class TorrentMixin(RssStoreBase):
    def record_item_torrent_links(self, item_hash, links):
        with self._conn() as conn:
            exist = conn.execute("SELECT hash FROM item_torrent_links WHERE hash=?", (item_hash,)).fetchone()
            if exist:
                old = json.loads(conn.execute("SELECT links FROM item_torrent_links WHERE hash=?", (item_hash,)).fetchone()["links"] or "[]")
                merged = list(dict.fromkeys(list(old) + list(links)))
                conn.execute("UPDATE item_torrent_links SET links=?, scanned_at=datetime('now','localtime') WHERE hash=?", (json.dumps(merged), item_hash))
            else:
                conn.execute("INSERT OR IGNORE INTO item_torrent_links(hash,links,scanned_at) VALUES(?,?,datetime('now','localtime'))",
                             (item_hash, json.dumps(list(dict.fromkeys(links)))))
            if links:
                # D17: 原实现只查 links[0]，且无 btih 时写 "" 覆盖已有 torrent_hash 并置
                # hash_scan_state=2（阻止重扫）。改为遍历全部链接提取 btih，仅当提取到
                # 非空 btih 时才更新 items；空结果不动已有值/状态（条目可被再次扫描）。
                btih = ""
                for l in links:
                    h = extract_btih(l)
                    if h:
                        btih = h
                        break
                if btih:
                    conn.execute("UPDATE items SET hash_scan_state=2, torrent_hash=? WHERE hash=?",
                                 (btih, item_hash))

    def get_item_torrent_links(self, item_hash):
        with self._conn() as conn:
            row = conn.execute("SELECT links FROM item_torrent_links WHERE hash=?", (item_hash,)).fetchone()
        if not row:
            return []
        try:
            return json.loads(row["links"] or "[]")
        except Exception:
            return []

    def mark_hash_scan(self, hashes, state=1):
        if not hashes:
            return
        with self._conn() as conn:
            conn.executemany("UPDATE items SET hash_scan_state=? WHERE hash=?",
                             [(state, h) for h in hashes])

    def get_pending_hash_scans(self, limit=50, magnet_only=False):
        """返回待解析 hash 的条目（hash_scan_state=0）。magnet_only 时仅磁力/种子条目。"""
        with self._conn() as conn:
            sql = """SELECT hash,title,link,image_url FROM items
                     WHERE hash_scan_state=0 AND torrent_hash=''
                     {extra}
                     ORDER BY id DESC LIMIT ?"""
            extra = ""
            if magnet_only:
                extra = ("AND (link LIKE '%magnet:%' OR link LIKE '%.torrent'"
                         " OR EXISTS(SELECT 1 FROM item_feeds f WHERE f.hash=items.hash AND f.feed_id IN "
                         "(SELECT id FROM feeds WHERE is_torrent=1))"
                         " OR EXISTS(SELECT 1 FROM item_sources s WHERE s.hash=items.hash AND "
                         "(s.tag LIKE '%磁%' OR s.tag LIKE '%种子%' OR s.tag LIKE '%动漫%' OR s.tag LIKE '%动画%')))")
            rows = conn.execute(sql.format(extra=extra), (limit,)).fetchall()
        return [dict(r) for r in rows]