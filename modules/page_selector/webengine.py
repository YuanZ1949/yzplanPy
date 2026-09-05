"""页面选择器的 WebEngine 惰性加载（避免任何 import 路径拉起 Chromium 线程池）。"""
import logging
import sys

logger = logging.getLogger("page_selector")

def _webengine_view():
    """惰性导入 QWebEngineView：仅在真正打开选择器时才加载 WebEngine，
    避免任何 import 路径（含误 import 本模块）在启动期拉起 Chromium 线程池。"""
    mod = sys.modules.get("PySide6.QtWebEngineWidgets")
    if mod is not None:
        return getattr(mod, "QWebEngineView", None)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception as _we:  # pragma: no cover
        logger.warning("QtWebEngine 不可用，页面选择器将不可用: %s", _we)
        return None
    return QWebEngineView
