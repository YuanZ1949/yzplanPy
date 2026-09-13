"""rss_store.py: RSS 数据存储层，不依赖 Qt，可独立用于测试。

本文件已按职责拆分为 modules/rss_store/store_*.py 切片，此处保留为
re-export 总入口：RssStore 由各职责 mixin 组合而成，全部公开符号
（RssStore、函数、常量）与拆分前完全兼容。
"""
import base64
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from core.perf import trace

from .store_aggregation import AggregationMixin
from .store_categories import CategoriesMixin
from .store_cleanup import CleanupMixin
from .store_conn import (
    RssStoreBase,
    _default_category_hex,
    _default_keyword_hex,
    logger,
)
from .store_discover import DiscoverMixin
from .store_feeds import FeedsMixin
from .store_filter_rules import FilterRulesMixin
from .store_items import ItemsMixin
from .store_keywords import KeywordsMixin
from .store_opml import OpmlMixin
from .store_schema import SchemaMixin
from .store_search import SearchMixin
from .store_share import ShareMixin
from .store_stats import StatsMixin
from .store_torrent import TorrentMixin


class RssStore(
    FeedsMixin,
    ItemsMixin,
    TorrentMixin,
    SearchMixin,
    AggregationMixin,
    CategoriesMixin,
    KeywordsMixin,
    FilterRulesMixin,
    OpmlMixin,
    DiscoverMixin,
    CleanupMixin,
    StatsMixin,
    ShareMixin,
    SchemaMixin,
    RssStoreBase,
):
    """RSS 数据存储层：连接池 + schema 迁移 + 各职责 mixin 的组合类。"""


# --- package-slice imports (re-exported by modules/rss_store/__init__) ---
from .pure import (b32_to_hex, normalize_btih, extract_btih, _hash,
                   _normalize_published, _estimate_read_time, _extract_image,
                   _detect_encoding, _is_magnet_or_torrent,
                   _MAGNET_BTIH_RE, _MAGNET_BTIH_B32_RE, _HEX40_RE)
from .fetch import fetch_feed, scrape_page
from .scrapers_selector import scrape_html

__all__ = [
    "RssStore",
    "RssStoreBase",
    "FeedsMixin",
    "ItemsMixin",
    "TorrentMixin",
    "SearchMixin",
    "AggregationMixin",
    "CategoriesMixin",
    "KeywordsMixin",
    "FilterRulesMixin",
    "OpmlMixin",
    "DiscoverMixin",
    "CleanupMixin",
    "StatsMixin",
    "ShareMixin",
    "SchemaMixin",
    "logger",
    "_default_category_hex",
    "_default_keyword_hex",
    "b32_to_hex",
    "normalize_btih",
    "extract_btih",
    "_hash",
    "_normalize_published",
    "_estimate_read_time",
    "_extract_image",
    "_detect_encoding",
    "_is_magnet_or_torrent",
    "_MAGNET_BTIH_RE",
    "_MAGNET_BTIH_B32_RE",
    "_HEX40_RE",
    "fetch_feed",
    "scrape_page",
    "scrape_html",
]