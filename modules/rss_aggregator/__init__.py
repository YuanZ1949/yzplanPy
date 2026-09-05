"""rss_aggregator 模块：多源 RSS 聚合、合并去重、多来源标签标注。"""

import html.parser
import json
import logging
import os
import re
import sys
import threading
import warnings
import webbrowser

from core.qt_bootstrap import import_qt
from core.perf import timed
from ..base import ModuleBase
from ..rss_store import (RssStore, _hash, _is_magnet_or_torrent, fetch_feed,
                         scrape_page, export_opml_file, import_opml_file,
                         _extract_image, extract_btih)

logger = logging.getLogger("rss_aggregator")
warnings.filterwarnings("ignore", category=__import__("urllib3").exceptions.InsecureRequestWarning)
_, QtCore, QtGui, QtWidgets = import_qt()
PAGE_SIZE = 50

# ── 包内切片导入（reopen 类同名 rebind，末尾导入即最终类）────────────
from .text_utils import (_rss_colors, _rss_panel_colors, _QF, _qf, _parse_keywords,
                         _ALLOWED_TAGS, _ALLOWED_ATTRS, _URL_ATTRS, _SKIP_TAGS,
                         _VOID_TAGS, _Sanitizer, _sanitize_html)
from .preview import _PREVIEW_KEEP, _make_preview_view
from .fetchers import _Fetcher, _HashScanner, _TORRENT_HREF_RE, _MAGNET_BARE_RE
from .styles import _btn_style, _btn_primary_style, _sidebar_qss
from .utils import _bind_geometry, _decode_feed_icon, _FaviconWorker
from .rows import _TITLE_FONT_PX, _WrapRow, _HeadRow, _AutoRow, _pill_style
from .rows_item import _make_item_row
from .dialogs_a import _EditFeedDialog, _FeedManageDialog
from .dialogs_b import _AddFeedDialog
from .dialogs_c import _SettingsDialog
from .dialogs_d import _SettingsDialog
from .dialogs_e import _CategoryDialog, _FilterRuleDialog, _KeywordDialog
from .dialogs_f import _AddAggregationDialog
from .home import _RssHomeWidget
from .sidebar import _RssSidebar
from .sidebar_data import _RssSidebar
from .sidebar_actions import _RssSidebar
from .page import _RssPageWidget
from .page_lifecycle import _RssPageWidget
from .page_settings_build import _RssPageWidget
from .page_actions import _RssPageWidget
from .page_rows import _RssPageWidget
from .page_torrent import _RssPageWidget
from .page_batch import _RssPageWidget
from .page_preview import _RssPageWidget
from .page_context import _RssPageWidget
from .module import MODULE_INFO, Module