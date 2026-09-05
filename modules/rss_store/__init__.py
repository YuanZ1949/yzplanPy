"""modules/rss_store package - sliced from the original single-file module.

Re-exports the complete module-level surface of the original
modules/rss_store.py so all external importers keep working unchanged:
  RssStore, _hash, _is_magnet_or_torrent, b32_to_hex, normalize_btih,
  extract_btih, _normalize_published, _estimate_read_time, _extract_image,
  _detect_encoding, HtmlElement, _build_dom, find_elements, scrape_html,
  scrape_page, fetch_feed, export_opml_file, import_opml_file, _parse_selector
  (+ every other module-level name present in the original file)
"""

import logging

from .store import RssStore

from .pure import (
    _hash,
    _is_magnet_or_torrent,
    _MAGNET_BTIH_RE,
    _MAGNET_BTIH_B32_RE,
    _HEX40_RE,
    b32_to_hex,
    normalize_btih,
    extract_btih,
    _normalize_published,
    _estimate_read_time,
    _extract_image,
    _detect_encoding,
)

from .scrapers import (
    HtmlElement,
    _TreeBuilder,
    _build_dom,
    _normalize_text,
    _inner_html,
    _inner_text,
    _walk,
    _attr_match,
    _sibling_index,
    _sibling_of_type_index,
    _match_simple,
    _parse_simple,
    _split_top,
    _VOID_TAGS,
)

from .scrapers_selector import (
    _parse_selector,
    _match_chain,
    _match_one_chain,
    find_elements,
    _resolve_url,
    _value_from,
    _auto_link,
    scrape_html,
    _filter_by_keywords,
)

from .fetch import scrape_page, fetch_feed

from .opml import export_opml_file, import_opml_file

logger = logging.getLogger("rss_store")
