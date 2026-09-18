"""rss_store slice: schema init / migration mixin.

Spliced from modules/rss_store/store.py by store-split refactor.
"""
from .pure import b32_to_hex
from .store_conn import (
    RssStoreBase,
    _default_category_hex,
    _default_keyword_hex,
    logger,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_SIMILARITY_GRANULARITY,
)
from .store_schema_sql import _SCHEMA_SQL


class SchemaMixin(RssStoreBase):
    _SCHEMA_VERSION = 5

    def _init_schema(self):
        # 快速路径：数据库已由本版本初始化过，跳过全部幂等迁移（PRAGMA table_info 很贵）。
        try:
            ver = self._conn().execute("PRAGMA user_version").fetchone()[0]
            if ver >= self._SCHEMA_VERSION:
                self._schema_checked = True
                # 幂等数据迁移仍需在 fast-path 执行：v5 库可能残留
                # refresh_interval=1800 的存量行（迁移函数晚于版本号升级加入）。
                # UPDATE 无 1800 行时是 no-op，代价可忽略。
                conn = self._conn()
                self._migrate_default_refresh_interval(conn)
                # UPDATE（即便匹配 0 行）会开启隐式写事务；本连接被 _conn()
                # 按 (thread, db_path) 池化且进程内不关闭，不提交就会长期持有
                # RESERVED 写锁，导致其它模块写库时 "database is locked"。
                conn.commit()
                return
        except Exception:
            pass
        with self._conn() as conn:
            conn.executescript(
                _SCHEMA_SQL.replace("@CATEGORY_COLOR@", _default_category_hex()).replace(
                    "@KEYWORD_COLOR@", _default_keyword_hex())
            )
            self._ensure_column(conn, "feeds", "group_name", "TEXT DEFAULT ''")
            self._ensure_column(conn, "feeds", "refresh_interval", "INTEGER DEFAULT 21600")
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
                    last_refreshed TEXT,
                    similarity_granularity INTEGER DEFAULT 1
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
            self._ensure_column(conn, "categories", "color", f"TEXT DEFAULT '{_default_category_hex()}'")
            self._ensure_column(conn, "categories", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "filter_rules", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "filter_rules", "field", "TEXT DEFAULT 'title'")
            self._ensure_column(conn, "filter_rules", "operator", "TEXT DEFAULT 'contains'")
            self._ensure_column(conn, "filter_rules", "enabled", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "keywords", "color", f"TEXT DEFAULT '{_default_keyword_hex()}'")
            self._ensure_column(conn, "keywords", "notify", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "aggregations", "parent_id", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "aggregations", "similarity_threshold", f"REAL DEFAULT {DEFAULT_SIMILARITY_THRESHOLD}")
            self._ensure_column(conn, "aggregations", "similarity_granularity", f"INTEGER DEFAULT {DEFAULT_SIMILARITY_GRANULARITY}")
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
            try:
                # D5: 外部内容表(items_fts)建表时为空，触发器只对新行生效；
                # 旧库升级（已有存量 items）必须重建索引，否则 search() 部分命中时漏存量条目。
                conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            except Exception as ex:
                logger.warning("FTS 索引重建失败: %s", ex)
            self._migrate_default_refresh_interval(conn)
            try:
                conn.execute(f"PRAGMA user_version = {self._SCHEMA_VERSION}")
            except Exception:
                pass
            self._schema_checked = True

    def _migrate_default_refresh_interval(self, conn):
        """v4→v5：默认刷新间隔 1800s → 21600s（6 小时）。

        仅迁移仍停留在旧默认值 1800 的源；用户显式自定义的其它值（如 3600）
        一律不动。幂等：重复执行时已无 1800 行，UPDATE 为 no-op。
        """
        try:
            cur = conn.execute(
                "UPDATE feeds SET refresh_interval=21600 WHERE refresh_interval=1800"
            )
            if cur.rowcount:
                logger.info("刷新间隔迁移完成: %d 条 1800s → 21600s", cur.rowcount)
        except Exception as ex:
            logger.warning("刷新间隔迁移失败: %s", ex)

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