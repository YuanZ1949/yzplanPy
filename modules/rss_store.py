"""rss_store.py: RSS 数据存储层，不依赖 Qt，可独立用于测试。"""
import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from core.perf import trace

logger = logging.getLogger("rss_store")


class RssStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS feeds(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    tag TEXT,
                    enabled INTEGER DEFAULT 1,
                    group_name TEXT DEFAULT '',
                    refresh_interval INTEGER DEFAULT 1800,
                    last_refresh TEXT,
                    custom_headers TEXT DEFAULT '{}',
                    etag TEXT DEFAULT '',
                    last_modified TEXT DEFAULT '',
                    last_error TEXT DEFAULT '',
                    error_count INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS items(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT UNIQUE NOT NULL,
                    title TEXT,
                    link TEXT,
                    published TEXT,
                    description TEXT DEFAULT '',
                    image_url TEXT DEFAULT '',
                    read_time INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS item_sources(
                    hash TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY(hash, tag)
                );
                CREATE TABLE IF NOT EXISTS item_read(
                    hash TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS read_history(
                    hash TEXT PRIMARY KEY,
                    read_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS favorites(
                    hash TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    note TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS categories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#1a73e8',
                    sort_order INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS item_categories(
                    hash TEXT NOT NULL,
                    category_id INTEGER NOT NULL,
                    PRIMARY KEY(hash, category_id)
                );
                CREATE TABLE IF NOT EXISTS filter_rules(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    field TEXT DEFAULT 'title',
                    operator TEXT DEFAULT 'contains',
                    value TEXT NOT NULL,
                    action TEXT DEFAULT 'tag',
                    action_value TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS keywords(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT UNIQUE NOT NULL,
                    color TEXT DEFAULT '#ff6b6b',
                    notify INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS item_related(
                    hash1 TEXT NOT NULL,
                    hash2 TEXT NOT NULL,
                    similarity REAL DEFAULT 0.0,
                    PRIMARY KEY(hash1, hash2)
                );
                """
            )
            self._ensure_column(conn, "feeds", "group_name", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "refresh_interval", "INTEGER DEFAULT 1800")
            self._ensure_column(conn, "feeds", "custom_headers", "TEXT DEFAULT '{}'")
            self._ensure_column(conn, "feeds", "feed_type", "TEXT DEFAULT 'normal'")
            self._ensure_column(conn, "feeds", "scrape_options", "TEXT DEFAULT '{}'")
            self._ensure_column(conn, "feeds", "rendered", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "feeds", "last_refresh", "TEXT")
            self._ensure_column(conn, "feeds", "etag", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "last_modified", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "last_error", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "error_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "feeds", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "feeds", "icon", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "favicon_state", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "items", "description", "TEXT DEFAULT ''")
            self._ensure_column(conn, "items", "image_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "items", "read_time", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "items", "torrent_hash", "TEXT DEFAULT ''")
            self._ensure_column(conn, "items", "hash_scan_state", "INTEGER DEFAULT 0")
            self._ensure_table(conn, "item_torrent_links", """
                CREATE TABLE IF NOT EXISTS item_torrent_links(
                    hash TEXT PRIMARY KEY,
                    links TEXT DEFAULT '[]',
                    scanned_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_items_torrent_hash ON items(torrent_hash)")
            except Exception as ex:
                logger.warning("创建索引失败: %s", ex)
            self._ensure_column(conn, "feeds", "created_at", "TEXT DEFAULT ''")
            try:
                conn.execute("UPDATE feeds SET created_at=datetime('now','localtime') WHERE created_at IS NULL OR created_at=''")
            except Exception as ex:
                logger.warning("回填 created_at 失败: %s", ex)
            self._ensure_column(conn, "feeds", "is_torrent", "INTEGER DEFAULT 0")
            self._normalize_stored_btih(conn)
            self._ensure_table(conn, "item_feeds", """
                CREATE TABLE IF NOT EXISTS item_feeds(
                    hash TEXT NOT NULL,
                    feed_id INTEGER NOT NULL,
                    PRIMARY KEY(hash, feed_id)
                )
            """)
            self._ensure_table(conn, "feed_tags", """
                CREATE TABLE IF NOT EXISTS feed_tags(
                    feed_id INTEGER NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY(feed_id, tag)
                )
            """)
            try:
                conn.execute(
                    """UPDATE feeds SET is_torrent=1 WHERE id IN (
                       SELECT DISTINCT f.feed_id FROM item_feeds f
                       JOIN items i ON i.hash=f.hash WHERE i.torrent_hash!='')"""
                )
            except Exception as ex:
                logger.warning("回填 is_torrent 失败: %s", ex)
            self._ensure_table(conn, "aggregations", """
                CREATE TABLE IF NOT EXISTS aggregations(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    agg_type TEXT DEFAULT 'mixed',
                    feed_ids TEXT DEFAULT '[]',
                    tags TEXT DEFAULT '[]',
                    kw_required TEXT DEFAULT '[]',
                    kw_optional TEXT DEFAULT '[]',
                    kw_forbidden TEXT DEFAULT '[]',
                    sort_order INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    last_refreshed TEXT
                )
            """)
            self._ensure_table(conn, "aggregation_items", """
                CREATE TABLE IF NOT EXISTS aggregation_items(
                    agg_id INTEGER NOT NULL,
                    hash TEXT NOT NULL,
                    added_at TEXT DEFAULT (datetime('now','localtime')),
                    PRIMARY KEY(agg_id, hash)
                )
            """)
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_item_feeds_feed ON item_feeds(feed_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_items_agg ON aggregation_items(agg_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agg_items_added ON aggregation_items(agg_id, added_at)")
            except Exception as ex:
                logger.warning("创建聚合索引失败: %s", ex)
            self._backfill_item_feeds(conn)
            self._ensure_column(conn, "favorites", "created_at", "TEXT DEFAULT (datetime('now','localtime'))")
            self._ensure_column(conn, "favorites", "note", "TEXT DEFAULT ''")
            self._ensure_column(conn, "categories", "color", "TEXT DEFAULT '#1a73e8'")
            self._ensure_column(conn, "categories", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "filter_rules", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "filter_rules", "field", "TEXT DEFAULT 'title'")
            self._ensure_column(conn, "filter_rules", "operator", "TEXT DEFAULT 'contains'")
            self._ensure_column(conn, "filter_rules", "enabled", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "keywords", "color", "TEXT DEFAULT '#ff6b6b'")
            self._ensure_column(conn, "keywords", "notify", "INTEGER DEFAULT 1")
            self._ensure_table(conn, "read_history", """
                CREATE TABLE IF NOT EXISTS read_history(
                    hash TEXT PRIMARY KEY,
                    read_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            self._ensure_table(conn, "item_related", """
                CREATE TABLE IF NOT EXISTS item_related(
                    hash1 TEXT NOT NULL,
                    hash2 TEXT NOT NULL,
                    similarity REAL DEFAULT 0.0,
                    PRIMARY KEY(hash1, hash2)
                )
            """)
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(title, description, content=items, content_rowid=id)"
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN INSERT INTO items_fts(rowid, title, description) VALUES(new.id, new.title, new.description); END"
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN INSERT INTO items_fts(items_fts, rowid, title, description) VALUES('delete', old.id, old.title, old.description); END"
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN INSERT INTO items_fts(items_fts, rowid, title, description) VALUES('delete', old.id, old.title, old.description); INSERT INTO items_fts(rowid, title, description) VALUES(new.id, new.title, new.description); END"
                )
            except Exception:
                pass

    def _normalize_stored_btih(self, conn):
        """一次性的 BTIH 编码规范化迁移：把已入库的 32 位 Base32 hash 转为 40 位 hex，
        使同一磁力的不同编码（蜜柑 hex / 动漫花园 base32）能合并到同一聚合分组。"""
        try:
            rows = conn.execute(
                "SELECT hash, torrent_hash FROM items WHERE torrent_hash != '' AND length(torrent_hash)=32"
            ).fetchall()
            for r in rows:
                hx = b32_to_hex(r["torrent_hash"])
                if hx:
                    conn.execute(
                        "UPDATE items SET torrent_hash=? WHERE hash=? AND torrent_hash=?",
                        (hx, r["hash"], r["torrent_hash"]),
                    )
            if rows:
                logger.info("BTIH 规范化迁移完成: %d 条 base32 转 hex", len(rows))
        except Exception as ex:
            logger.warning("BTIH 规范化迁移失败: %s", ex)

    def _ensure_column(self, conn, table, column, definition):
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            existing = [r["name"] for r in rows]
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                logger.debug("添加列: %s.%s", table, column)
        except Exception as ex:
            logger.warning("添加列失败 %s.%s: %s", table, column, ex)

    def _ensure_table(self, conn, table, sql):
        try:
            conn.execute(f"SELECT 1 FROM {table} LIMIT 0")
        except Exception:
            try:
                conn.execute(sql)
                logger.debug("创建表: %s", table)
            except Exception as ex:
                logger.warning("创建表失败 %s: %s", table, ex)

    def _backfill_item_feeds(self, conn):
        """把既有条目的来源标签订单映射到订阅源（标签→feeds.tag 尽力回填 item_feeds）。"""
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM item_feeds").fetchone()["c"]
        except Exception:
            return
        if count:
            return
        try:
            rows = conn.execute("SELECT id, tag FROM feeds").fetchall()
            tag_to_fids = {}
            for r in rows:
                tag_to_fids.setdefault(r["tag"], []).append(r["id"])
            for tag, fids in tag_to_fids.items():
                if not tag:
                    continue
                hashes = conn.execute("SELECT DISTINCT hash FROM item_sources WHERE tag=?", (tag,)).fetchall()
                for hr in hashes:
                    for fid in fids:
                        conn.execute("INSERT OR IGNORE INTO item_feeds(hash, feed_id) VALUES(?,?)", (hr["hash"], fid))
            logger.debug("回填 item_feeds 完成")
        except Exception as ex:
            logger.warning("回填 item_feeds 失败: %s", ex)

    # ── Feed 管理 ──────────────────────────────────────────────
    def list_feeds(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM feeds ORDER BY sort_order, group_name, name").fetchall()
        feeds = [dict(r) for r in rows]
        for f in feeds:
            f["tags"] = self.get_feed_tags(f["id"])
        return feeds

    def list_feed_groups(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT group_name FROM feeds ORDER BY group_name"
            ).fetchall()
        return [r["group_name"] for r in rows if r["group_name"]]

    def add_feed(self, name, url, tag, group_name="", refresh_interval=1800, custom_headers=None, feed_type="normal", scrape_options=None, rendered=0, tags=None):
        tags = [t for t in (tags or ([tag] if tag else [name])) if t]
        first_tag = tags[0] if tags else (tag or name)
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feeds(name,url,tag,enabled,group_name,refresh_interval,custom_headers,feed_type,scrape_options,rendered,created_at) VALUES(?,?,?,1,?,?,?,?,?,?,datetime('now','localtime'))",
                (name, url, first_tag, group_name or "", refresh_interval, json.dumps(custom_headers or {}),
                 feed_type, json.dumps(scrape_options or {}), 1 if rendered else 0),
            )
            fid = conn.execute("SELECT id FROM feeds WHERE name=?", (name,)).fetchone()
            if fid:
                conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (fid["id"],))
                conn.executemany(
                    "INSERT OR IGNORE INTO feed_tags(feed_id, tag) VALUES(?,?)",
                    [(fid["id"], t) for t in tags],
                )

    def update_feed(self, feed_id, **kwargs):
        allowed = {"name", "url", "tag", "enabled", "group_name", "refresh_interval", "custom_headers", "etag", "last_modified", "last_error", "error_count", "sort_order", "feed_type", "scrape_options", "rendered", "icon", "favicon_state"}
        if kwargs.get("scrape_options") is not None and not isinstance(kwargs.get("scrape_options"), str):
            kwargs["scrape_options"] = json.dumps(kwargs["scrape_options"])
        tags = kwargs.pop("tags", None)
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if tags is None and not updates:
            return
        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [feed_id]
            with self._conn() as conn:
                conn.execute(f"UPDATE feeds SET {sets} WHERE id=?", vals)
        if tags is not None:
            self.set_feed_tags(feed_id, tags)

    def remove_feed(self, feed_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
            conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (feed_id,))

    def set_feed_enabled(self, feed_id, enabled):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET enabled=? WHERE id=?", (1 if enabled else 0, feed_id))

    def set_feed_is_torrent(self, feed_id, is_torrent):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET is_torrent=? WHERE id=?", (1 if is_torrent else 0, feed_id))

    def get_feed_is_torrent(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT is_torrent FROM feeds WHERE id=?", (feed_id,)).fetchone()
        return bool(row and row["is_torrent"])

    def set_feed_error(self, feed_id, error_msg):
        with self._conn() as conn:
            conn.execute(
                "UPDATE feeds SET last_error=?, error_count=error_count+1 WHERE id=?",
                (error_msg, feed_id),
            )

    def clear_feed_error(self, feed_id):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET last_error='', error_count=0 WHERE id=?", (feed_id,))

    def update_feed_order(self, feed_ids):
        with self._conn() as conn:
            for idx, fid in enumerate(feed_ids):
                conn.execute("UPDATE feeds SET sort_order=? WHERE id=?", (idx, fid))

    def get_feed_by_id(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()
        d = dict(row) if row else None
        if d:
            d["tags"] = self.get_feed_tags(feed_id)
        return d

    def get_feed_tags(self, feed_id):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tag FROM feed_tags WHERE feed_id=? ORDER BY tag", (feed_id,)
            ).fetchall()
        return [r["tag"] for r in rows]

    def set_feed_tags(self, feed_id, tags):
        tags = [t for t in (tags or []) if t]
        with self._conn() as conn:
            conn.execute("DELETE FROM feed_tags WHERE feed_id=?", (feed_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO feed_tags(feed_id, tag) VALUES(?,?)",
                [(feed_id, t) for t in tags],
            )
            legacy = tags[0] if tags else ""
            conn.execute("UPDATE feeds SET tag=? WHERE id=?", (legacy, feed_id))

    def update_feed_refresh_time(self, feed_id):
        with self._conn() as conn:
            conn.execute(
                "UPDATE feeds SET last_refresh=datetime('now','localtime') WHERE id=?",
                (feed_id,),
            )

    def get_feeds_needing_refresh(self):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM feeds
                WHERE enabled = 1 AND (
                    last_refresh IS NULL
                    OR datetime(last_refresh, '+' || refresh_interval || ' seconds') <= datetime('now','localtime')
                )
                ORDER BY sort_order
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def search_feeds(self, query):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feeds WHERE name LIKE ? OR url LIKE ? OR tag LIKE ? ORDER BY name",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
        feeds = [dict(r) for r in rows]
        for f in feeds:
            f["tags"] = self.get_feed_tags(f["id"])
        return feeds

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
        return added

    def list_tags(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT tag FROM item_sources ORDER BY tag"
            ).fetchall()
        return [r["tag"] for r in rows]

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

    # ── 搜索 ──────────────────────────────────────────────────
    def search(self, query, limit=200, offset=0, field=None, date_from=None, date_to=None):
        with self._conn() as conn:
            conditions = []
            params = []
            if field == "title":
                conditions.append("i.title LIKE ?")
                params.append(f"%{query}%")
            elif field == "description":
                conditions.append("i.description LIKE ?")
                params.append(f"%{query}%")
            elif field == "link":
                conditions.append("i.link LIKE ?")
                params.append(f"%{query}%")
            else:
                try:
                    rows = conn.execute(
                        "SELECT rowid FROM items_fts WHERE items_fts MATCH ?",
                        (query,),
                    ).fetchall()
                    if rows:
                        fts_ids = [r["rowid"] for r in rows]
                        placeholders = ",".join("?" * len(fts_ids))
                        conditions.append(f"i.id IN ({placeholders})")
                        params.extend(fts_ids)
                    else:
                        conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                        params.extend([f"%{query}%", f"%{query}%"])
                except Exception:
                    conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                    params.extend([f"%{query}%", f"%{query}%"])
            if date_from:
                conditions.append("i.published >= ?")
                params.append(date_from)
            if date_to:
                conditions.append("i.published <= ?")
                params.append(date_to)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.extend([limit, offset])
            rows = conn.execute(
                f"""
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                       GROUP_CONCAT(s.tag, ' | ') AS tags,
                       CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                       CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                FROM items i
                LEFT JOIN item_sources s ON i.hash = s.hash
                LEFT JOIN item_read r ON i.hash = r.hash
                LEFT JOIN favorites f ON i.hash = f.hash
                {where}
                GROUP BY i.hash
                ORDER BY i.published DESC, i.id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 列表查询 ──────────────────────────────────────────────
    def recent(self, limit=100, tag_filter=None, category_id=None, favorites_only=False, unread_only=False,
               date_range=None, feed_ids=None, tags=None, keyword=None, torrent_hash=None, agg_id=None):
        with self._conn() as conn:
            conditions = []
            params = []
            if feed_ids:
                # 精确到订阅源：item_feeds 关联
                ph = ",".join("?" * len(feed_ids))
                conditions.append("i.hash IN (SELECT hash FROM item_feeds WHERE feed_id IN (%s))" % ph)
                params.extend(list(feed_ids))
            if tags:
                ph3 = ",".join("?" * len(tags))
                conditions.append("i.hash IN (SELECT hash FROM item_sources WHERE tag IN (%s))" % ph3)
                params.extend(tags)
            if agg_id:
                conditions.append("i.hash IN (SELECT hash FROM aggregation_items WHERE agg_id = ?)")
                params.append(agg_id)
            if torrent_hash:
                conditions.append("i.torrent_hash = ?")
                params.append(torrent_hash)
            if keyword:
                conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
                kw = "%{}%".format(keyword)
                params.append(kw)
                params.append(kw)
            if favorites_only:
                conditions.append("f.hash IS NOT NULL")
            if unread_only:
                conditions.append("r.hash IS NULL")
            if tag_filter == "__磁链__":
                conditions.append("(i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
            elif tag_filter == "__文章__":
                conditions.append("NOT (i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
            elif tag_filter:
                conditions.append("i.hash IN (SELECT hash FROM item_sources WHERE tag = ?)")
                params.append(tag_filter)
            if category_id:
                conditions.append("i.hash IN (SELECT hash FROM item_categories WHERE category_id = ?)")
                params.append(category_id)
            if date_range == "today":
                conditions.append("i.published >= date('now', 'localtime', '-1 day')")
            elif date_range == "week":
                conditions.append("i.published >= date('now', 'localtime', '-7 days')")
            elif date_range == "month":
                conditions.append("i.published >= date('now', 'localtime', '-1 month')")
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                       GROUP_CONCAT(s.tag, ' | ') AS tags,
                       CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                       CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                FROM items i
                LEFT JOIN item_sources s ON i.hash = s.hash
                LEFT JOIN item_read r ON i.hash = r.hash
                LEFT JOIN favorites f ON i.hash = f.hash
                {where}
                GROUP BY i.hash
                ORDER BY i.published DESC, i.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 侧边栏 / 聚合节点数据 ──────────────────────────────
    def list_sidebar(self):
        """返回侧边栏所需的节点数据与计数。
        返回 dict: {feeds:[{id,name,tag,group_name,icon,feed_type,enabled,unread,created_at,last_refresh}],
                    aggregations:[{id,name,agg_type,feed_ids,tags,kw_*,created_at,last_refreshed,count,unread}]}"""
        with self._conn() as conn:
            feeds = conn.execute(
                "SELECT id,name,tag,group_name,icon,feed_type,enabled,created_at,last_refresh FROM feeds"
            ).fetchall()
            feed_nodes = []
            for f in feeds:
                unread_row = conn.execute(
                    """SELECT COUNT(DISTINCT i.hash) AS c FROM items i
                       LEFT JOIN item_read r ON i.hash=r.hash
                       LEFT JOIN item_feeds f ON i.hash=f.hash
                       WHERE f.feed_id=? AND r.hash IS NULL""",
                    (f["id"],),
                ).fetchone()
                d = dict(f)
                d["unread"] = unread_row["c"] if unread_row else 0
                d["tags"] = [
                    r["tag"] for r in conn.execute(
                        "SELECT tag FROM feed_tags WHERE feed_id=? ORDER BY tag", (f["id"],)
                    ).fetchall()
                ]
                feed_nodes.append(d)
            aggs = conn.execute(
                "SELECT * FROM aggregations ORDER BY sort_order, created_at"
            ).fetchall()
            agg_nodes = []
            for a in aggs:
                d = dict(a)
                d["count"] = conn.execute(
                    "SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (d["id"],)
                ).fetchone()["c"]
                unr = conn.execute(
                    """SELECT COUNT(*) AS c FROM aggregation_items ai
                       LEFT JOIN item_read r ON ai.hash=r.hash
                       WHERE ai.agg_id=? AND r.hash IS NULL""",
                    (d["id"],),
                ).fetchone()
                d["unread"] = unr["c"] if unr else 0
                agg_nodes.append(d)
        return {"feeds": feed_nodes, "aggregations": agg_nodes}

    # ── 聚合（手动，独立快照） ──────────────────────────────
    def list_aggregations(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM aggregations ORDER BY sort_order, created_at").fetchall()
        return [dict(r) for r in rows]

    def get_aggregation(self, agg_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM aggregations WHERE id=?", (agg_id,)).fetchone()
        return dict(row) if row else None

    def add_aggregation(self, name, agg_type="mixed", feed_ids=None, tags=None,
                        kw_required=None, kw_optional=None, kw_forbidden=None, sort_order=0):
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO aggregations(name,agg_type,feed_ids,tags,kw_required,kw_optional,kw_forbidden,sort_order)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (name, agg_type,
                 json.dumps(feed_ids or []), json.dumps(tags or []),
                 json.dumps(kw_required or []), json.dumps(kw_optional or []), json.dumps(kw_forbidden or []),
                 sort_order),
            )
            return cur.lastrowid

    def update_aggregation(self, agg_id, **kwargs):
        allowed = {"name", "agg_type", "feed_ids", "tags", "kw_required", "kw_optional", "kw_forbidden",
                   "sort_order", "enabled"}
        for k in ("feed_ids", "tags", "kw_required", "kw_optional", "kw_forbidden"):
            if k in kwargs and not isinstance(kwargs[k], str) and kwargs[k] is not None:
                kwargs[k] = json.dumps(kwargs[k])
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [agg_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE aggregations SET {sets} WHERE id=?", vals)

    def remove_aggregation(self, agg_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
            conn.execute("DELETE FROM aggregations WHERE id=?", (agg_id,))

    @staticmethod
    def _keyword_clauses(agg):
        """按三桶关键词生成 SQL 条件（AND 关系）。
        必须(required)：每个命中 title|desc；可选(optional)：至少一个（OR，空=不限）；
        禁止(forbidden)：每个都不得命中。返回 (conditions, params)。"""
        conditions = []
        params = []
        req = json.loads(agg.get("kw_required") or "[]")
        opt = json.loads(agg.get("kw_optional") or "[]")
        forb = json.loads(agg.get("kw_forbidden") or "[]")
        for k in req:
            p = "%{}%".format(k)
            conditions.append("(i.title LIKE ? OR i.description LIKE ?)")
            params.extend([p, p])
        if opt:
            parts = []
            for k in opt:
                p = "%{}%".format(k)
                parts.append("(i.title LIKE ? OR i.description LIKE ?)")
                params.extend([p, p])
            conditions.append("(" + " OR ".join(parts) + ")")
        for k in forb:
            p = "%{}%".format(k)
            conditions.append("NOT (i.title LIKE ? OR i.description LIKE ?)")
            params.extend([p, p])
        return conditions, params

    def refresh_aggregation(self, agg_id):
        """重建聚合快照：取成员(订阅源/标签)的已入库条目 → 按类型过滤 → 写入 aggregation_items。"""
        agg = self.get_aggregation(agg_id)
        if not agg or not agg.get("enabled"):
            return 0
        feed_ids = json.loads(agg.get("feed_ids") or "[]")
        tags = json.loads(agg.get("tags") or "[]")
        agg_type = agg.get("agg_type") or "mixed"
        scope = []
        params = []
        if feed_ids:
            ph = ",".join("?" * len(feed_ids))
            scope.append("i.hash IN (SELECT hash FROM item_feeds WHERE feed_id IN (%s))" % ph)
            params.extend(feed_ids)
        if tags:
            ph2 = ",".join("?" * len(tags))
            scope.append("i.hash IN (SELECT hash FROM item_sources WHERE tag IN (%s))" % ph2)
            params.extend(tags)
        if agg_type == "torrent":
            scope.append("(i.torrent_hash != '' OR i.link LIKE '%magnet:%' OR i.link LIKE '%.torrent')")
        elif agg_type == "keyword":
            kc, kp = self._keyword_clauses(agg)
            scope.extend(kc)
            params.extend(kp)
        with self._conn() as conn:
            if not scope:
                conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
                conn.execute("UPDATE aggregations SET last_refreshed=datetime('now','localtime') WHERE id=?", (agg_id,))
                return 0
            where = " AND ".join(scope)
            rows = conn.execute(f"SELECT DISTINCT i.hash AS hash FROM items i WHERE {where}", params).fetchall()
            conn.execute("DELETE FROM aggregation_items WHERE agg_id=?", (agg_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO aggregation_items(agg_id, hash) VALUES(?,?)",
                [(agg_id, r["hash"]) for r in rows],
            )
            conn.execute("UPDATE aggregations SET last_refreshed=datetime('now','localtime') WHERE id=?", (agg_id,))
        return len(rows)

    def get_aggregation_torrent_groups(self, agg_id, limit=200):
        """磁链hash类型聚合：按 torrent_hash 分组，供方案B 折叠/展开渲染。"""
        with self._conn() as conn:
            sql = """
                SELECT i.torrent_hash AS hash,
                       COUNT(DISTINCT i.hash) AS count,
                       COUNT(DISTINCT fi.feed_id) AS feed_count,
                       (SELECT i2.title FROM items i2 WHERE i2.torrent_hash=i.torrent_hash ORDER BY i2.id DESC LIMIT 1) AS title
                FROM aggregation_items ai
                JOIN items i ON i.hash=ai.hash
                LEFT JOIN item_feeds fi ON fi.hash=i.hash
                WHERE ai.agg_id=?
                GROUP BY i.torrent_hash
                ORDER BY MAX(i.published) DESC, COUNT(DISTINCT i.hash) DESC
                """
            if limit:
                sql += " LIMIT ?"
                rows = conn.execute(sql, (agg_id, limit)).fetchall()
            else:
                rows = conn.execute(sql, (agg_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_aggregation_torrent_items(self, agg_id, torrent_hash):
        """磁链hash类型聚合：某分组(hash)内的成员条目（回退全文）。"""
        with self._conn() as conn:
            if torrent_hash:
                rows = conn.execute(
                    """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                              GROUP_CONCAT(s.tag, ' | ') AS tags,
                              CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                              CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                       FROM aggregation_items ai
                       JOIN items i ON i.hash=ai.hash
                       LEFT JOIN item_sources s ON i.hash=s.hash
                       LEFT JOIN item_read r ON i.hash=r.hash
                       LEFT JOIN favorites f ON i.hash=f.hash
                       WHERE ai.agg_id=? AND i.torrent_hash=?
                       GROUP BY i.hash ORDER BY i.published DESC, i.id DESC""",
                    (agg_id, torrent_hash),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                              GROUP_CONCAT(s.tag, ' | ') AS tags,
                              CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                              CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                       FROM aggregation_items ai
                       JOIN items i ON i.hash=ai.hash
                       LEFT JOIN item_sources s ON i.hash=s.hash
                       LEFT JOIN item_read r ON i.hash=r.hash
                       LEFT JOIN favorites f ON i.hash=f.hash
                       WHERE ai.agg_id=? AND (i.torrent_hash='' OR i.torrent_hash IS NULL)
                       GROUP BY i.hash ORDER BY i.published DESC, i.id DESC""",
                    (agg_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_all_aggregation_torrent_items(self, agg_id):
        """一次查询获取整个聚合的所有成员条目，按 torrent_hash 分组返回 {hash: [items]}。"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url, i.torrent_hash,
                          GROUP_CONCAT(s.tag, ' | ') AS tags,
                          CASE WHEN r.hash IS NOT NULL THEN 1 ELSE 0 END AS read,
                          CASE WHEN f.hash IS NOT NULL THEN 1 ELSE 0 END AS favorite
                   FROM aggregation_items ai
                   JOIN items i ON i.hash=ai.hash
                   LEFT JOIN item_sources s ON i.hash=s.hash
                   LEFT JOIN item_read r ON i.hash=r.hash
                   LEFT JOIN favorites f ON i.hash=f.hash
                   WHERE ai.agg_id=?
                   GROUP BY i.hash ORDER BY i.torrent_hash, i.published DESC, i.id DESC""",
                (agg_id,),
            ).fetchall()
        grouped = {}
        for r in rows:
            d = dict(r)
            th = d.get("torrent_hash") or ""
            grouped.setdefault(th, []).append(d)
        return grouped

    def get_torrent_group_items(self, torrent_hash, limit=500):
        return self.recent(limit=limit, torrent_hash=torrent_hash, tag_filter=None)

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
                conn.execute("UPDATE items SET hash_scan_state=2, torrent_hash=? WHERE hash=?",
                             (extract_btih(links[0]) or "", item_hash))

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

    def set_feed_icon(self, feed_id, data):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET icon=?, favicon_state=2 WHERE id=?", (data or "", feed_id))

    def get_feed_icon(self, feed_id):
        with self._conn() as conn:
            row = conn.execute("SELECT icon FROM feeds WHERE id=?", (feed_id,)).fetchone()
        return (row["icon"] if row else "") or ""

    def feeds_needing_favicon(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT id,name,url FROM feeds WHERE favicon_state=0 AND enabled=1").fetchall()
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

    # ── 分类 ──────────────────────────────────────────────────
    def get_categories(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
        return [dict(r) for r in rows]

    def add_category(self, name, color="#1a73e8"):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO categories(name,color) VALUES(?,?)", (name, color))

    def remove_category(self, category_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
            conn.execute("DELETE FROM item_categories WHERE category_id=?", (category_id,))

    def update_category(self, category_id, name=None, color=None):
        with self._conn() as conn:
            if name is not None:
                conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
            if color is not None:
                conn.execute("UPDATE categories SET color=? WHERE id=?", (color, category_id))

    def set_item_category(self, item_hash, category_id):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO item_categories(hash,category_id) VALUES(?,?)",
                (item_hash, category_id),
            )

    def remove_item_category(self, item_hash, category_id):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM item_categories WHERE hash=? AND category_id=?",
                (item_hash, category_id),
            )

    def get_item_categories(self, item_hash):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.color
                FROM categories c
                INNER JOIN item_categories ic ON c.id = ic.category_id
                WHERE ic.hash = ?
                """,
                (item_hash,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 过滤规则 ──────────────────────────────────────────────
    def get_filter_rules(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM filter_rules ORDER BY sort_order, id").fetchall()
        return [dict(r) for r in rows]

    def add_filter_rule(self, name, field, operator, value, action, action_value=""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO filter_rules(name,field,operator,value,action,action_value) VALUES(?,?,?,?,?,?)",
                (name, field, operator, value, action, action_value),
            )

    def remove_filter_rule(self, rule_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM filter_rules WHERE id=?", (rule_id,))

    def update_filter_rule(self, rule_id, enabled=None):
        with self._conn() as conn:
            if enabled is not None:
                conn.execute("UPDATE filter_rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))

    def apply_filter_rules(self, entries):
        rules = self.get_filter_rules()
        for entry in entries:
            for rule in rules:
                if not rule["enabled"]:
                    continue
                field_val = entry.get(rule["field"], "")
                match = False
                if rule["operator"] == "contains":
                    match = rule["value"].lower() in field_val.lower()
                elif rule["operator"] == "not_contains":
                    match = rule["value"].lower() not in field_val.lower()
                elif rule["operator"] == "equals":
                    match = rule["value"].lower() == field_val.lower()
                elif rule["operator"] == "starts_with":
                    match = field_val.lower().startswith(rule["value"].lower())
                elif rule["operator"] == "ends_with":
                    match = field_val.lower().endswith(rule["value"].lower())
                elif rule["operator"] == "regex":
                    try:
                        match = bool(re.search(rule["value"], field_val, re.IGNORECASE))
                    except re.error:
                        pass
                if match:
                    if rule["action"] == "tag":
                        entry["extra_tag"] = rule["action_value"]
                    elif rule["action"] == "skip":
                        entry["_skip"] = True
                    elif rule["action"] == "highlight":
                        entry["_highlight"] = True
        return entries

    # ── 关键词 ────────────────────────────────────────────────
    def get_keywords(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM keywords ORDER BY keyword").fetchall()
        return [dict(r) for r in rows]

    def add_keyword(self, keyword, color="#ff6b6b", notify=1):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO keywords(keyword,color,notify) VALUES(?,?,?)",
                (keyword, color, notify),
            )

    def remove_keyword(self, keyword_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))

    def check_keywords(self, title, description=""):
        keywords = self.get_keywords()
        matched = []
        text = f"{title} {description}".lower()
        for kw in keywords:
            if kw["keyword"].lower() in text:
                matched.append(kw)
        return matched

    # ── OPML ──────────────────────────────────────────────────
    def export_opml(self):
        root = ET.Element("opml", version="2.0")
        head = ET.SubElement(root, "head")
        title = ET.SubElement(head, "title")
        title.text = "YZplan RSS Subscriptions"
        body = ET.SubElement(root, "body")
        groups = {}
        for f in self.list_feeds():
            grp = f.get("group_name", "") or "未分组"
            if grp not in groups:
                groups[grp] = ET.SubElement(body, "outline", text=grp)
            folder = groups[grp]
            attrs = {
                "text": f["name"],
                "title": f["name"],
                "type": "rss",
                "xmlUrl": f["url"],
                "htmlUrl": f["url"],
            }
            if f.get("tag"):
                attrs["description"] = f"标签: {f['tag']}"
            ET.SubElement(folder, "outline", **attrs)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    def import_opml(self, opml_content):
        root = ET.fromstring(opml_content)
        count = 0
        for body in root.iter("body"):
            for group_outline in body.findall("outline"):
                group_name = group_outline.get("text", "")
                for outline in group_outline.findall("outline"):
                    xml_url = outline.get("xmlUrl")
                    if xml_url:
                        name = outline.get("text") or outline.get("title") or xml_url
                        tag = ""
                        desc = outline.get("description", "")
                        if desc.startswith("标签: "):
                            tag = desc[4:]
                        self.add_feed(name, xml_url, tag or name, group_name)
                        count += 1
            for outline in body.findall("outline"):
                xml_url = outline.get("xmlUrl")
                if xml_url:
                    name = outline.get("text") or outline.get("title") or xml_url
                    tag = ""
                    desc = outline.get("description", "")
                    if desc.startswith("标签: "):
                        tag = desc[4:]
                    self.add_feed(name, xml_url, tag or name, "")
                    count += 1
        return count

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


# ── 辅助函数 ──────────────────────────────────────────────────
def _hash(title, link):
    norm = "{}|{}".format((title or "").strip().lower(), (link or "").strip().lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def _is_magnet_or_torrent(link):
    if not link:
        return False
    lower = link.strip().lower()
    if lower.startswith("magnet:"):
        return True
    if lower.endswith(".torrent"):
        return True
    return False


_MAGNET_BTIH_RE = re.compile(r"[?&]xt=urn:btih:([0-9a-fA-F]{40})")
# BTIH 支持两种编码：40 位十六进制 或 32 位 Base32(A-Z2-7，不含 0/1/8/9)
_MAGNET_BTIH_B32_RE = re.compile(r"[?&]xt=urn:btih:([A-Za-z2-7]{32})")
_HEX40_RE = re.compile(r"\b([0-9a-fA-F]{40})\b")


def b32_to_hex(b32):
    """32 位 Base32 BTIH -> 40 位小写十六进制。非法输入返回 None。"""
    if not b32:
        return None
    s = b32.strip().upper()
    if len(s) != 32 or not all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in s):
        return None
    try:
        raw = base64.b32decode(s)
    except Exception:
        return None
    return raw.hex()


def normalize_btih(value):
    """将任意 BTIH 编码规范化为 40 位小写十六进制。无法识别返回原样。"""
    if not value:
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("ascii")
        except Exception:
            return value
    s = value.strip()
    if len(s) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in s):
        return s.lower()
    if len(s) == 32:
        hx = b32_to_hex(s)
        if hx:
            return hx
    return value


def extract_btih(link):
    """从链接/文本中提取磁力 info-hash 并规范化为 40 位小写十六进制。
    支持 40 位 hex 与 32 位 Base32 BTIH 两种编码。无则返回空。"""
    if not link:
        return ""
    if isinstance(link, str):
        m = _MAGNET_BTIH_RE.search(link)
        if m:
            return m.group(1).lower()
        m = _MAGNET_BTIH_B32_RE.search(link)
        if m:
            return normalize_btih(m.group(1)) or ""
        # 纯 hash 或磁力/种子名里内嵌的连续 40 位 hex
        m = _HEX40_RE.search(link)
        if m:
            return m.group(1).lower()
    return ""


def _normalize_published(published):
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
        return dt.isoformat()
    except Exception:
        pass
    return published


def _estimate_read_time(description):
    if not description:
        return 1
    text = re.sub(r"<[^>]+>", "", description)
    words = len(text.split())
    return max(1, words // 200)


def _extract_image(description, link=""):
    if not description:
        return ""
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _detect_encoding(content):
    try:
        import chardet
        result = chardet.detect(content[:4096])
        return result.get("encoding") or "utf-8"
    except ImportError:
        return "utf-8"


# ── 页面监控：轻量 HTML DOM + CSS 选择器引擎 ──────────────────────
# 仅依赖标准库 (html.parser)，不依赖 lxml/bs4/Qt，可独立测试。

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class HtmlElement:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.text = ""

    def get(self, name, default=""):
        v = self.attrs.get(name.lower())
        return default if v is None else v


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlElement("#root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        parent = self._stack[-1]
        node = HtmlElement(tag, dict(attrs), parent)
        parent.children.append(node)
        if tag not in _VOID_TAGS and not self._is_void_like(tag):
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        parent = self._stack[-1]
        node = HtmlElement(tag, dict(attrs), parent)
        parent.children.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return
        # 未匹配的结束标签：忽略

    def handle_data(self, data):
        if self._stack:
            self._stack[-1].text += data

    def _is_void_like(self, tag):
        return False


def _build_dom(html):
    builder = _TreeBuilder()
    try:
        builder.feed(html or "")
        builder.close()
    except Exception:
        pass
    return builder.root


def _normalize_text(text):
    import re as _re
    if not text:
        return ""
    return _re.sub(r"\s+", " ", text).strip()


def _inner_html(node):
    return _inner_text(node)


def _inner_text(node):
    parts = [node.text or ""]
    for c in node.children:
        parts.append(_inner_text(c))
    return _normalize_text("".join(parts))


def _walk(node):
    if node is None:
        return
    yield node
    for c in node.children:
        yield from _walk(c)


def _attr_match(node, name, op, value):
    val = node.get(name)
    if op == "exists":
        return val != ""
    val = val or ""
    value = value or ""
    if op == "=":
        return val == value
    if op == "^=":
        return val.startswith(value)
    if op == "$=":
        return val.endswith(value)
    if op == "*=":
        return value in val
    if op == "~=":
        return value in val.split()
    if op == "|=":
        return val == value or val.startswith(value + "-")
    return False


def _sibling_index(node):
    """返回 node 在同级中的下标（0 基）。"""
    if node.parent is None:
        return 0
    return node.parent.children.index(node)


def _sibling_of_type_index(node):
    """返回 node 在同类标签兄弟中的下标（0 基）。"""
    if node.parent is None:
        return 0
    return [c for c in node.parent.children if c.tag == node.tag].index(node)


def _match_simple(node, token):
    """匹配单一选择器片段，如 tag、.class、#id、[attr=val]、*、:nth-child(n)。"""
    tag, cls, ident, attr, pseudos = token
    if tag and tag != "*" and node.tag != tag.lower():
        return False
    for c in cls:
        if c not in node.get("class", "").split():
            return False
    if ident and node.get("id") != ident:
        return False
    for name, op, value in attr:
        if not _attr_match(node, name, op, value):
            return False
    for pname, parg in pseudos:
        if pname == "nth-child":
            if _sibling_index(node) + 1 != parg:
                return False
        elif pname == "nth-of-type":
            if _sibling_of_type_index(node) + 1 != parg:
                return False
        elif pname in ("first-child", "last-child", "first-of-type", "last-of-type"):
            is_first = _sibling_index(node) == 0
            is_last = (node.parent is not None) and _sibling_index(node) == len(node.parent.children) - 1
            is_first_type = _sibling_of_type_index(node) == 0
            is_last_type = (node.parent is not None) and _sibling_of_type_index(node) == len(
                [c for c in node.parent.children if c.tag == node.tag]
            ) - 1
            if pname == "first-child" and not is_first:
                return False
            if pname == "last-child" and not is_last:
                return False
            if pname == "first-of-type" and not is_first_type:
                return False
            if pname == "last-of-type" and not is_last_type:
                return False
    return True


def _parse_simple(token_str):
    """把形如 'div.a#b[href^=x]:nth-child(2)' 解析为 (tag,[classes],id,[attr],[pseudo])"""
    import re as _re
    tag = ""
    classes = []
    ident = ""
    attrs = []
    pseudos = []
    rest = token_str.strip()
    m = _re.match(r"^[\w-]+", rest)
    if m:
        tag = m.group(0)
        rest = rest[m.end():]
    while rest:
        if rest.startswith("."):
            mm = _re.match(r"\.([\w-]+)", rest)
            if mm:
                classes.append(mm.group(1))
                rest = rest[mm.end():]
                continue
        if rest.startswith("#"):
            mm = _re.match(r"#([\w-]+)", rest)
            if mm:
                ident = mm.group(1)
                rest = rest[mm.end():]
                continue
        if rest.startswith(":"):
            mm = _re.match(r":([\w-]+)(?:\((.*?)\))?", rest)
            if mm:
                name = mm.group(1).lower()
                arg = mm.group(2)
                if name == "nth-child" and arg is not None:
                    try:
                        pseudos.append((name, int(arg.strip())))
                    except ValueError:
                        pass
                elif name == "nth-of-type" and arg is not None:
                    try:
                        pseudos.append((name, int(arg.strip())))
                    except ValueError:
                        pass
                elif name in ("first-child", "last-child", "first-of-type", "last-of-type"):
                    pseudos.append((name, None))
                rest = rest[mm.end():]
                continue
        if rest.startswith("["):
            mm = _re.match(r"\[([\w:-]+)([\^$*~|]?=)?(.*?)\]", rest)
            if mm:
                name = mm.group(1).lower()
                op = mm.group(2) or "exists"
                value = mm.group(3).strip().strip("\"'")
                attrs.append((name, op, value))
                rest = rest[mm.end():]
                continue
        break
    return tag, classes, ident, attrs, pseudos


def _split_top(text, sep):
    parts = []
    depth = 0
    cur = ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]


def _parse_selector(selector):
    """支持: 逗号组合、后代' '、子代'>'；返回一组 chain，每个 chain 为 [(token, 与上一个的组合器), ...]。"""
    groups = []
    for group in _split_top(selector, ","):
        chain = []
        comb = " "
        for part in re.split(r"\s+", group.strip()):
            if part == ">":
                comb = ">"
                continue
            if part:
                chain.append((_parse_simple(part), comb))
                comb = " "
        if chain:
            groups.append(chain)
    return groups


def _match_chain(groups, node):
    return any(_match_one_chain(chain, node) for chain in groups)


def _match_one_chain(chain, node):
    if not chain:
        return False
    tok, _comb = chain[-1]
    if not _match_simple(node, tok):
        return False
    cur = node.parent
    for tok, comb in reversed(chain[:-1]):
        if cur is None:
            return False
        if comb == ">":
            if not _match_simple(cur, tok):
                return False
            cur = cur.parent
        else:
            while cur is not None and not _match_simple(cur, tok):
                cur = cur.parent
            if cur is None:
                return False
            cur = cur.parent
    return True


def find_elements(dom, selector):
    if not selector or not selector.strip():
        return []
    groups = _parse_selector(selector)
    return [n for n in _walk(dom) if n.tag and n.tag != "#root" and _match_chain(groups, n)]


def _resolve_url(base, href):
    from urllib.parse import urljoin
    if not base or not href:
        return href or ""
    if href.startswith("//"):
        scheme = base.split(":", 1)[0] if ":" in base else "http"
        return scheme + ":" + href
    return urljoin(base, href)


def _value_from(node, spec, base_url):
    """按 spec 从元素提取字符串值。spec: {sel, attr, text}"""
    if not spec:
        return ""
    sel = spec.get("sel")
    attr = spec.get("attr")
    if sel:
        matches = find_elements(node, sel)
        target = matches[0] if matches else None
    else:
        target = node
    if target is None:
        return ""
    if attr:
        val = target.get(attr)
        if attr.lower() in ("href", "src") and val:
            return _resolve_url(base_url, val)
        return val or ""
    return _inner_text(target)


def _auto_link(node, base_url):
    """当 item.link 未指定时，自动为条目挑选对应元素的链接：
    元素本身是链接，或取其子树中第一个 <a href>；没有则返回空。"""
    if node is None:
        return ""
    href = node.get("href")
    if href:
        return _resolve_url(base_url, href)
    for n in _walk(node):
        if n is not node and n.tag == "a" and n.get("href"):
            return _resolve_url(base_url, n.get("href"))
    return ""


def scrape_html(html, options, base_url=""):
    """从 HTML 中按选项提取 RSS 条目。返回 entries 列表（与 fetch_feed 同结构）。"""
    if not html or not options:
        return []
    mode = options.get("mode", "list")
    selector = options.get("selector") or ""
    dom = _build_dom(html)
    nodes = find_elements(dom, selector)
    if not nodes:
        return []

    item_spec = options.get("item") or {}
    title_spec = item_spec.get("title") or {}
    link_spec = item_spec.get("link") or {}
    content_spec = item_spec.get("content") or {}
    max_items = int(options.get("max_items", 100) or 100)

    def make_entry(node):
        title = _value_from(node, title_spec, base_url) or _inner_text(node)
        link = _value_from(node, link_spec, base_url) or _auto_link(node, base_url)
        content = _value_from(node, content_spec, base_url)
        from datetime import datetime as _dt
        published = _dt.now().isoformat()
        image = ""
        img = next((n for n in _walk(node) if n.tag == "img"), None)
        if img is not None:
            src = img.get("src")
            if src:
                image = _resolve_url(base_url, src)
        return {
            "title": title,
            "link": link,
            "published": published,
            "description": content or _inner_html(node),
            "image_url": image,
        }

    entries = []
    if mode == "single":
        entries = [make_entry(nodes[0])] if nodes else []
    else:
        for n in nodes[:max_items]:
            entries.append(make_entry(n))
    entries = _filter_by_keywords(entries, options.get("keywords") or [])
    return entries


def _filter_by_keywords(entries, keywords):
    """关键词过滤：默认空列表接受全部；否则保留标题或描述包含任一关键词的条目。"""
    kws = [(k or "").strip().lower() for k in keywords]
    kws = [k for k in kws if k]
    if not kws:
        return entries
    result = []
    for e in entries:
        text = "{} {}".format(e.get("title", ""), e.get("description", "")).lower()
        if any(k in text for k in kws):
            result.append(e)
    return result


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


def export_opml_file(store, file_path):
    opml = store.export_opml()
    Path(file_path).write_text(opml, encoding="utf-8")
    return True


def import_opml_file(store, file_path):
    content = Path(file_path).read_text(encoding="utf-8")
    return store.import_opml(content)
