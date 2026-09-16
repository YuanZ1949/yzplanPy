"""rss_store slice: connection pool + module-level helpers.

Spliced from modules/rss_store/store.py by store-split refactor.
RssStoreBase 提供连接池与实例初始化；其余方法由各职责 mixin 提供。
"""
import logging
import os
import sqlite3
import threading

logger = logging.getLogger("rss_store")

# 相似性聚合默认值（单一来源，供 schema 迁移 / add_aggregation / 页面回退共用，避免漂移）
DEFAULT_SIMILARITY_THRESHOLD = 0.55
DEFAULT_SIMILARITY_GRANULARITY = 1
MAX_SIMILARITY_GRANULARITY = 10


def _default_category_hex():
    """分类默认色：延迟从主题令牌解析，保持本模块模块级不依赖 Qt。"""
    from core.theme.tokens import theme_palette
    return theme_palette()["status_info"]


def _default_keyword_hex():
    """关键词监控默认高亮色：延迟从主题令牌解析，保持本模块模块级不依赖 Qt。"""
    from core.theme.tokens import theme_palette
    return theme_palette()["rss_keyword_color"]


class RssStoreBase:
    """RssStore 连接池与实例初始化（其余方法由各职责 mixin 提供）。"""

    _conn_registry = {}      # (thread_id, id(instance)) -> sqlite3.Connection
    _conn_registry_lock = threading.Lock()

    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._schema_checked = False
        self._tags_cache = None
        self._keywords_cache = None
        self._init_schema()

    def _init_schema(self):
        """由 SchemaMixin 提供；基类占位（RssStore 组合后经 MRO 由 SchemaMixin 覆盖）。"""
        raise NotImplementedError

    # ── 跨 mixin 契约占位（由对应职责 mixin 覆盖，仅供静态分析/文档） ──
    def list_feeds(self):
        """由 FeedsMixin 提供。"""
        raise NotImplementedError

    def add_feed(self, name, url, tag, group_name="", refresh_interval=1800,
                 custom_headers=None, feed_type="normal", scrape_options=None,
                 rendered=0, tags=None):
        """由 FeedsMixin 提供。"""
        raise NotImplementedError

    def get_item(self, item_hash):
        """由 ItemsMixin 提供。"""
        raise NotImplementedError

    def recent(self, limit=100, tag_filter=None, category_id=None, favorites_only=False,
               unread_only=False, date_range=None, feed_ids=None, tags=None, keyword=None,
               torrent_hash=None, agg_id=None):
        """由 SearchMixin 提供。"""
        raise NotImplementedError

    def _conn_key(self):
        # 用 db_path 而非 id(instance)：实例被回收后 id 可能被复用，
        # 否则新实例会命中旧实例遗留的连接（连到错误/已废弃的库文件）。
        return (threading.get_ident(), os.path.abspath(self.db_path))

    def _conn(self):
        key = self._conn_key()
        with self._conn_registry_lock:
            conn = self._conn_registry.get(key)
            if conn is None:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                self._conn_registry[key] = conn
                if len(self._conn_registry) > 32:
                    self._prune_conns_locked()
            return conn

    def _prune_conns_locked(self):
        live = {t.ident for t in threading.enumerate()}
        for k in [k for k in self._conn_registry if k[0] not in live]:
            c = self._conn_registry.pop(k, None)
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    def _close_conn(self):
        key = self._conn_key()
        with self._conn_registry_lock:
            conn = self._conn_registry.pop(key, None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass