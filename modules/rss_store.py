"""rss_store.py: RSS 数据存储层，不依赖 Qt，可独立用于测试。"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

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
            self._ensure_column(conn, "feeds", "last_refresh", "TEXT")
            self._ensure_column(conn, "feeds", "etag", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "last_modified", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "last_error", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "error_count", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "feeds", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "items", "description", "TEXT DEFAULT ''")
            self._ensure_column(conn, "items", "image_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "items", "read_time", "INTEGER DEFAULT 0")
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

    # ── Feed 管理 ──────────────────────────────────────────────
    def list_feeds(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM feeds ORDER BY sort_order, group_name, name").fetchall()
        return [dict(r) for r in rows]

    def list_feed_groups(self):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT group_name FROM feeds ORDER BY group_name"
            ).fetchall()
        return [r["group_name"] for r in rows if r["group_name"]]

    def add_feed(self, name, url, tag, group_name="", refresh_interval=1800, custom_headers=None):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feeds(name,url,tag,enabled,group_name,refresh_interval,custom_headers) VALUES(?,?,?,1,?,?,?)",
                (name, url, tag or name, group_name or "", refresh_interval, json.dumps(custom_headers or {})),
            )

    def update_feed(self, feed_id, **kwargs):
        allowed = {"name", "url", "tag", "enabled", "group_name", "refresh_interval", "custom_headers", "etag", "last_modified", "last_error", "error_count", "sort_order"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [feed_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE feeds SET {sets} WHERE id=?", vals)

    def remove_feed(self, feed_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))

    def set_feed_enabled(self, feed_id, enabled):
        with self._conn() as conn:
            conn.execute("UPDATE feeds SET enabled=? WHERE id=?", (1 if enabled else 0, feed_id))

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
        return dict(row) if row else None

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
        return [dict(r) for r in rows]

    # ── Item 管理 ──────────────────────────────────────────────
    def ingest(self, tag, entries):
        added = 0
        with self._conn() as conn:
            for e in entries:
                title = e.get("title") or (e.get("link") or "")
                link = e.get("link") or ""
                published = e.get("published", "")
                description = e.get("description", "")
                image_url = e.get("image_url", "")
                h = _hash(title, link)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO items(hash,title,link,published,description,image_url) VALUES(?,?,?,?,?,?)",
                    (h, title, link, _normalize_published(published), description, image_url),
                )
                if cur.rowcount:
                    added += 1
                conn.execute(
                    "INSERT OR IGNORE INTO item_sources(hash,tag) VALUES(?,?)",
                    (h, tag),
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
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url,
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
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url,
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
    def recent(self, limit=100, tag_filter=None, category_id=None, favorites_only=False, unread_only=False, date_range=None):
        with self._conn() as conn:
            conditions = []
            params = []
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
                SELECT i.hash, i.title, i.link, i.published, i.description, i.image_url,
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
                entries.append(
                    {
                        "title": e.get("title", ""),
                        "link": e.get("link", ""),
                        "published": e.get("published", ""),
                        "description": desc,
                        "image_url": image,
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
