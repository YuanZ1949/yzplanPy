"""页面选择器：用 QtWebEngine 打开网页，通过鼠标点选/多选/关键词/手动输入 CSS 选择器，
为「页面监控 RSS 源」锁定目标元素并生成可被 rss_store 引擎解析的选择器配置。

仅供交互使用；实际抓取由 rss_store.scrape_html / scrape_page 完成（纯 Python）。
"""
import logging
import sys

from core.qt_bootstrap import import_qt
from ..rss_store import scrape_html as _backend_scrape_html, _parse_selector

logger = logging.getLogger("page_selector")

_, QtCore, QtGui, QtWidgets = import_qt()

from .webengine import _webengine_view
from .picker_js import _PICKER_JS
from .dialog_actions import PageSelectorDialog

__all__ = ["PageSelectorDialog", "_PICKER_JS", "_webengine_view"]