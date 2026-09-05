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
from .base import ModuleBase
from .rss_store import (
    RssStore, _hash, _is_magnet_or_torrent, fetch_feed, scrape_page,
    export_opml_file, import_opml_file, _extract_image,
    extract_btih,
)

logger = logging.getLogger("rss_aggregator")

# 抓取这些源时有意使用 verify=False 绕过有问题的证书，屏蔽对应的告警
warnings.filterwarnings("ignore", category=__import__("urllib3").exceptions.InsecureRequestWarning)

_, QtCore, QtGui, QtWidgets = import_qt()

PAGE_SIZE = 50


def _rss_colors():
    """一组主题感知的 RSS 样式色板（明暗两套），供各处列表/按钮/标签统一取色。

    半透明背景保证文字清晰且壁纸可见；无壁纸时也回退为接近全局 QSS 的面板观感。
    """
    try:
        from core.theme import resolve_dark
        dark = resolve_dark("auto")
    except Exception:
        dark = True
    if dark:
        return {
            "dark": True,
            "panel": "rgba(30,30,30,0.55)",
            "panel_soft": "rgba(30,30,30,0.45)",
            "panel_card": "rgba(255,255,255,0.05)",
            "border": "rgba(255,255,255,0.08)",
            "border_strong": "rgba(255,255,255,0.16)",
            # 主强调色
            "accent": "#4aa3ff",
            "accent_hover": "#6eb6ff",
            "accent_pressed": "#2f8ae6",
            "accent_bg": "rgba(74,163,255,0.16)",
            # 文字
            "text": "#e8e8e8",
            "text_secondary": "#9a9a9a",
            "text_faint": "#76767a",
            "title_unread": "#ffffff",
            "title_read": "#8a8a8a",
            # 控件（按钮/输入/下拉）
            "control_bg": "rgba(255,255,255,0.06)",
            "control_bg_hover": "rgba(255,255,255,0.12)",
            "control_border": "rgba(255,255,255,0.10)",
            "control_border_hover": "rgba(255,255,255,0.22)",
            # 标签药丸
            "pill_tag_bg": "rgba(74,163,255,0.18)",
            "pill_tag_fg": "#8fc2ff",
            "pill_torrent_bg": "rgba(255,107,107,0.16)",
            "pill_torrent_fg": "#ff9a9a",
            "pill_article_bg": "rgba(37,205,150,0.16)",
            "pill_article_fg": "#7fe0c0",
            # 徽标/收藏
            "badge_bg": "rgba(74,163,255,0.22)",
            "badge_fg": "#9cc8ff",
            "fav_color": "#ffc107",
            # 列表行
            "row_hover": "rgba(255,255,255,0.05)",
            "row_selected": "rgba(0,120,215,0.30)",
            # 玻璃面板 / 分隔 / 未读圆点
            "header_bg": "rgba(255,255,255,0.05)",
            "header_border": "rgba(255,255,255,0.10)",
            "card_border": "rgba(255,255,255,0.10)",
            "divider": "rgba(255,255,255,0.06)",
            "dot_unread": "#4aa3ff",
            "dot_read": "rgba(255,255,255,0.16)",
        }
    return {
        "dark": False,
        "panel": "rgba(245,245,245,0.60)",
        "panel_soft": "rgba(245,245,245,0.50)",
        "panel_card": "rgba(255,255,255,0.85)",
        "border": "rgba(0,0,0,0.08)",
        "border_strong": "rgba(0,0,0,0.14)",
        "accent": "#1a73e8",
        "accent_hover": "#1557b0",
        "accent_pressed": "#104d9a",
        "accent_bg": "rgba(26,115,232,0.10)",
        "text": "#1f1f1f",
        "text_secondary": "#666666",
        "text_faint": "#999999",
        "title_unread": "#111111",
        "title_read": "#9a9a9a",
        "control_bg": "rgba(255,255,255,0.90)",
        "control_bg_hover": "rgba(0,0,0,0.06)",
        "control_border": "rgba(0,0,0,0.14)",
        "control_border_hover": "rgba(0,0,0,0.26)",
        "pill_tag_bg": "#e8f0fe",
        "pill_tag_fg": "#1967d2",
        "pill_torrent_bg": "#fce8e6",
        "pill_torrent_fg": "#c5221f",
        "pill_article_bg": "#e6f4ea",
        "pill_article_fg": "#137333",
        "badge_bg": "#e8f0fe",
        "badge_fg": "#1967d2",
        "fav_color": "#ffb300",
        "row_hover": "rgba(0,120,215,0.07)",
        "row_selected": "rgba(0,120,215,0.18)",
        "header_bg": "rgba(255,255,255,0.72)",
        "header_border": "rgba(0,0,0,0.10)",
        "card_border": "rgba(0,0,0,0.10)",
        "divider": "rgba(0,0,0,0.06)",
        "dot_unread": "#1a73e8",
        "dot_read": "rgba(0,0,0,0.16)",
    }


def _rss_panel_colors():
    """兼容旧用法：只返回页面板背景色三项。"""
    c = _rss_colors()
    return {"panel": c["panel"], "panel_soft": c["panel_soft"], "border": c["border"]}


_QF = None


def _qf():
    """按需导入并缓存 qfluentwidgets 组件/图标，避免拖慢模块导入。"""
    global _QF
    if _QF is None:
        from qfluentwidgets import (  # noqa: F401
            CaptionLabel, CheckBox, ComboBox, DropDownPushButton, FluentIcon,
            IconWidget, PrimaryDropDownPushButton, PushButton, PrimaryPushButton,
            PrimaryToolButton, RoundMenu, SearchLineEdit, StrongBodyLabel, ToggleButton,
            ToolButton, TransparentToolButton,
        )
        _QF = dict(
            CaptionLabel=CaptionLabel, CheckBox=CheckBox, ComboBox=ComboBox,
            DropDownPushButton=DropDownPushButton, FluentIcon=FluentIcon,
            IconWidget=IconWidget, PrimaryDropDownPushButton=PrimaryDropDownPushButton,
            PushButton=PushButton, PrimaryPushButton=PrimaryPushButton,
            PrimaryToolButton=PrimaryToolButton,
            RoundMenu=RoundMenu, SearchLineEdit=SearchLineEdit,
            StrongBodyLabel=StrongBodyLabel,
            ToggleButton=ToggleButton, ToolButton=ToolButton,
            TransparentToolButton=TransparentToolButton,
        )
    return _QF


def _parse_keywords(text):
    """把用户输入的关键词文本（逗号/空格/换行分隔）解析为去重后的列表。"""
    parts = []
    for raw in re.split(r"[,，\s]+", text or ""):
        tok = raw.strip()
        if tok and tok not in parts:
            parts.append(tok)
    return parts


# ── 预览 HTML 白名单净化（标准库）──────────────
_ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "strike", "sub", "sup",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code", "hr", "div", "span", "table", "thead",
    "tbody", "tr", "th", "td", "caption",
    "a", "img", "figure", "figcaption", "audio", "video", "source",
}
_ALLOWED_ATTRS = {"href", "src", "title", "alt", "width", "height", "colspan", "rowspan", "controls", "poster", "loop", "muted"}
_URL_ATTRS = {"href": "http", "src": "http", "poster": "http"}
# 连同内容一起整体移除的危险/无关标签
_SKIP_TAGS = {
    "script", "style", "iframe", "object", "embed", "form", "input",
    "button", "svg", "math", "link", "meta", "base", "noscript", "template",
}
# HTML 空元素：无内容、无结束标签
_VOID_TAGS = {
    "br", "hr", "img", "source", "input", "meta", "link", "area",
    "base", "col", "wbr", "param", "track", "embed",
}


class _Sanitizer(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._stack = []  # 记录已开放的非 void 标签帧: (kind, tag)

    @staticmethod
    def _clean_attrs(attrs):
        cleaned = []
        for key, val in attrs:
            key = key.lower()
            if key not in _ALLOWED_ATTRS or key.startswith("on"):
                continue
            val = (val or "").strip()
            if key in _URL_ATTRS:
                low = val.lower()
                if not (low.startswith(("http:", "https:", "//", "/")) or low.startswith("data:image/")):
                    continue
            cleaned.append((key, val))
        return "".join(f' {k}="{_Sanitizer._escape_attr(v)}"' for k, v in cleaned)

    @staticmethod
    def _escape_attr(v):
        return (v or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        is_void = tag in _VOID_TAGS
        if tag in _SKIP_TAGS:
            if not is_void:
                self._stack.append(("skip", tag))
            return
        if tag not in _ALLOWED_TAGS:
            if not is_void:
                self._stack.append(("omit", tag))
            return
        if not is_void:
            kind = "a" if tag == "a" else "normal"
            self._stack.append((kind, tag))
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}/>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID_TAGS or not self._stack:
            return
        kind, t = self._stack.pop()
        if kind == "skip":
            return
        if t == tag and tag in _ALLOWED_TAGS:
            self.out.append(f"</{t}>")

    def handle_data(self, data):
        if any(kind == "skip" for kind, _t in self._stack):
            return
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def _sanitize_html(src):
    """净化不可信的 HTML（RSS 描述/网页内容），仅保留白名单标签与安全属性。"""
    if not src:
        return ""
    p = _Sanitizer()
    try:
        p.feed(src)
        p.close()
    except Exception:
        return ""
    return "".join(p.out)


# ── 安全预览用的 QWebEngine 视图 ──────────────
# 预览视图/页面/Profile 需常驻：若 Python 包装被 GC 回收，shiboken 会在渲染
# 子进程仍引用其 C++ 对象时删除它，导致崩溃（日志里全是
# "Garbage-collecting / 0x8001010d / Aborted"）。因此只保留最近一个视图，
# 模块窗口关闭时对象随窗口同步销毁（安全），重新打开时重建。
_PREVIEW_KEEP = {"view": None, "page": None, "profile": None, "render_process_alive": True}


def _make_preview_view(parent=None):
    """创建只读、禁用 JS、外链走系统浏览器的安全网页视图。
    返回 (view, available)。WebEngine 不可用时 available 为 False。"""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings

        def open_external(url):
            webbrowser.open(str(url))

        class _SafePage(QWebEnginePage):
            def __init__(self, profile):
                super().__init__(profile)

            def acceptNavigationRequest(self, url, typ, isMainFrame):
                if typ == QWebEnginePage.NavigationTypeLinkClicked:
                    open_external(url.toString())
                    return False
                return super().acceptNavigationRequest(url, typ, isMainFrame)

        # 无边框（Acrylic）窗口内嵌 WebEngine 需要组合拳，否则 DWM 合成被打断
        # 会出现窗口闪烁/标题栏发黑（看起来像"关闭后重开新窗口"）：
        # 1) 创建原生子窗口前给窗口开透明背景；2) 创建后立即 setHtml("")；
        # 3) 子窗口挂入后再 updateFrameless() 重刷帧边（在 addWidget 后执行）。
        try:
            win = parent.window() if parent is not None else None
            if win is not None:
                from qframelesswindow import AcrylicWindow
                if isinstance(win, AcrylicWindow):
                    win.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        except Exception:
            pass

        # 使用 defaultProfile 共享单个 Chromium 子进程：旧代码每次创建
        # QWebEngineProfile()（匿名 off-the-record）都会拉起独立 Chromium
        # 子进程；当渲染进程崩溃后 _on_terminated 清理引用 → 下次点击再建
        # → 新子进程又崩 → 线程数无限增长（性能监测可观察到）。
        profile = QWebEngineProfile.defaultProfile()  # 共享 Chromium 进程
        try:
            view = QWebEngineView()
        except Exception:
            return None, False
        try:
            view.setHtml("")
        except Exception:
            pass
        page = _SafePage(profile)
        view.setPage(page)
        # 同时作用于 profile 与 view/page settings，关闭脚本等危险能力
        js_off = [QWebEngineSettings.JavascriptEnabled, QWebEngineSettings.JavascriptCanOpenWindows,
                  QWebEngineSettings.JavascriptCanAccessClipboard, QWebEngineSettings.JavascriptCanPaste]
        for settings in (profile.settings(), view.settings()):
            for attr in js_off + [QWebEngineSettings.PluginsEnabled, QWebEngineSettings.AllowRunningInsecureContent,
                                  QWebEngineSettings.HyperlinkAuditingEnabled, QWebEngineSettings.WebGLEnabled,
                                  QWebEngineSettings.ScreenCaptureEnabled]:
                settings.setAttribute(attr, False)
            settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
        _PREVIEW_KEEP["view"] = view
        _PREVIEW_KEEP["page"] = page
        _PREVIEW_KEEP["profile"] = profile
        _PREVIEW_KEEP["render_process_alive"] = True
        # 有存活的 QtWebEngine 预览期间禁止任何位置强制 gc.collect()：
        # 立即回收其 shiboken 包装会在渲染子进程仍引用它时触发 0x8001010d/
        # Aborted 崩溃（crash_faulthandler.log 反复出现）。主线程定期 GC 定时器
        # 会通过 core.perf.webengine_alive() 查询并跳过本次收集。
        try:
            from core.perf import mark_webengine_alive
            mark_webengine_alive(True)
        except Exception:
            pass
        # 生命周期监测：加载/终止事件全部落日志，崩溃前后可精确对照
        logger.info("WebEngine 预览视图已创建 parent=%s pid=%s flags=%s",
                    type(parent).__name__ if parent is not None else None,
                    os.getpid(), os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))

        def _on_load_started():
            logger.debug("WebEngine 预览开始加载")

        def _on_load_finished(ok):
            logger.info("WebEngine 预览加载完成 ok=%s", ok)

        def _on_terminated(status, code):
            logger.error("QtWebEngine 渲染进程终止 status=%s exitCode=%s", status, code)
            # 渲染进程死掉：清除全局引用 + 标记死亡。
            # 下次 _ensure_preview_web 发现 render_process_alive=False 时
            # 不再创建新 QWebEngineProfile（每次创建都会拉起独立 Chromium
            # 子进程，线程数无限增长），直接回退到文本预览。
            _PREVIEW_KEEP["render_process_alive"] = False
            _PREVIEW_KEEP["view"] = None
            _PREVIEW_KEEP["page"] = None
            _PREVIEW_KEEP["profile"] = None
            try:
                from core.perf import mark_webengine_alive
                mark_webengine_alive(False)
            except Exception:
                pass

        def _on_url_changed(url):
            logger.debug("WebEngine 预览 URL=%s", url.toString())

        view.loadStarted.connect(_on_load_started)
        view.loadFinished.connect(_on_load_finished)
        view.renderProcessTerminated.connect(_on_terminated)
        view.urlChanged.connect(_on_url_changed)
        return view, True
    except Exception as e:  # pragma: no cover
        logger.warning("WebEngine 不可用，预览将使用文本模式: %s", e)
        return None, False


MODULE_INFO = {
    "id": "rss_aggregator",
    "name": "RSS 聚合",
    "description": "多来源聚合、去重与来源标签标注",
}


class Module(ModuleBase):
    MODULE_ID = "rss_aggregator"
    MODULE_NAME = "RSS 聚合"
    MODULE_DESCRIPTION = "多来源聚合、去重与来源标签标注"

    def __init__(self, context):
        super().__init__(context)
        from core.constants import DB_PATH
        self.store = RssStore(DB_PATH)
        self._timer = None
        self._thread = None
        self._scan_thread = None
        self._scan_running = False
        self._widgets = []
        self._notification_callback = None
        self._proxy = context.config.get("rss.proxy", "")
        self._retry_count = 3
        self._retry_delay = 5

    def start(self):
        if self._running:
            return
        super().start()
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60 * 1000)
        self._auto_refresh()
        if self.context.config.get("rss.auto_cleanup", False):
            self.store.cleanup_old(self.context.config.get("rss.cleanup_days", 30))
        if self.context.config.get("rss.auto_hash_scan", False):
            QtCore.QTimer.singleShot(3000, self.scan_hashes)
        logger.info("RSS模块已启动")

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        # 清理全局 WebEngine 预览引用，防止模块重载/重启时残留无效对象
        global _PREVIEW_KEEP
        _PREVIEW_KEEP["view"] = None
        _PREVIEW_KEEP["page"] = None
        _PREVIEW_KEEP["profile"] = None
        _PREVIEW_KEEP["render_process_alive"] = True
        try:
            from core.perf import mark_webengine_alive
            mark_webengine_alive(False)
        except Exception:
            pass
        super().stop()
        logger.info("RSS模块已停止")

    def trigger_preview(self, hash_, link):
        """触发指定条目的预览（通过 MCP inbox 调用）。"""
        try:
            for w in self._widgets:
                if hasattr(w, "_show_preview_by_hash"):
                    w._show_preview_by_hash(str(hash_), str(link or ""))
                    break
        except Exception as e:
            logger.debug("trigger_preview 失败: %s", e)

    def scan_hashes(self, limit=200):
        """后台启动磁链 hash 扫描（限速）。已在扫描则忽略。"""
        if self._scan_running or self._scan_thread is not None:
            return
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._scanner = _HashScanner(
            self.store, self._proxy,
            retry_count=self._retry_count, retry_delay=self._retry_delay,
            rate_limit_ms=self.context.config.get("rss.scan_rate_limit_ms", 1000),
        )
        self._scanner.done.connect(self._on_scan_done)
        self._scan_running = True
        self._scan_thread = threading.Thread(target=self._scanner.run, kwargs={"limit": limit, "magnet_only": True}, daemon=True)
        self._scan_thread.start()

    def _on_scan_done(self, scanned):
        self._scan_running = False
        self._scan_thread = None
        for w in list(self._widgets):
            try:
                w.on_hash_scan_done(scanned)
            except RuntimeError:
                self._forget_widget(w)

    def refresh_favicons(self):
        """后台抓取缺少 favicon 的订阅源图标。"""
        if getattr(self, "_fav_thread", None) is not None and self._fav_thread.is_alive():
            return
        self._fav = _FaviconWorker(self.store, self._proxy)
        self._fav.done.connect(self._on_fav_done)
        self._fav_thread = threading.Thread(target=self._fav.run, daemon=True)
        self._fav_thread.start()

    def _on_fav_done(self):
        self._fav_thread = None
        for w in list(self._widgets):
            try:
                w.on_favicons_loaded()
            except RuntimeError:
                self._forget_widget(w)

    def set_notification_callback(self, callback):
        self._notification_callback = callback

    def set_proxy(self, proxy):
        self._proxy = proxy or ""
        logger.info("RSS代理已更新: %s", self._proxy or "无")

    def _auto_refresh(self):
        feeds = self.store.get_feeds_needing_refresh()
        if feeds and self._thread is None:
            logger.debug("自动刷新触发, %d个源需要更新", len(feeds))
            self._do_refresh(feeds)

    def refresh_now(self):
        feeds = [f for f in self.store.list_feeds() if f["enabled"]]
        if not feeds or self._thread is not None:
            return
        logger.info("手动刷新, %d个源", len(feeds))
        self._do_refresh(feeds)

    def _do_refresh(self, feeds):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        max_workers = self.context.config.get("rss.async_workers", 4)
        self._fetcher = _Fetcher(feeds, self.store, self._proxy, self._retry_count, self._retry_delay, max_workers)
        self._fetcher.finished.connect(self._on_refreshed)
        self._fetcher.item_added.connect(self._on_item_added)
        self._fetcher.feed_done.connect(self._on_feed_done)
        self._thread = threading.Thread(target=self._fetcher.run, daemon=True)
        self._thread.start()

    def _on_item_added(self, item_info):
        if self._notification_callback:
            self._notification_callback(item_info)

    def _on_feed_done(self, info):
        # 每源完成即通知所有页面实时刷新（侧边栏计数 + 列表）
        # 并刷新该订阅源所属的手动聚合快照
        feed_id = (info or {}).get("feed_id")
        try:
            self.refresh_aggs_for_feed(feed_id)
        except Exception as ex:
            logger.warning("feed done 刷新聚合失败: %s", ex)
        for w in list(self._widgets):
            try:
                w.on_feed_done(info)
            except RuntimeError:
                self._forget_widget(w)

    def refresh_aggs_for_feed(self, feed_id):
        """刷新包含该订阅源的所有手动聚合的快照（纯 SQL，无网络）。"""
        if not feed_id:
            return
        for a in self.store.list_aggregations():
            feed_ids = json.loads(a.get("feed_ids") or "[]")
            if feed_id in feed_ids:
                try:
                    self.store.refresh_aggregation(a["id"])
                except Exception as ex:
                    logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)

    def refresh_aggregation(self, agg_id):
        self.store.refresh_aggregation(agg_id)
        for w in list(self._widgets):
            try:
                w.on_feed_done({})
            except RuntimeError:
                self._forget_widget(w)

    def refresh_all_aggregations(self):
        for a in self.store.list_aggregations():
            try:
                self.store.refresh_aggregation(a["id"])
            except Exception as ex:
                logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)
        for w in list(self._widgets):
            try:
                w.on_feed_done({})
            except RuntimeError:
                self._forget_widget(w)

    def _on_refreshed(self, counts):
        self._thread = None
        for w in list(self._widgets):
            try:
                w.on_refreshed(counts)
            except RuntimeError:
                self._forget_widget(w)
        if self.context.config.get("rss.auto_hash_scan", False):
            self._maybe_auto_scan()

    def _maybe_auto_scan(self):
        if self._scan_running or self._scan_thread is not None:
            return
        if self.store.get_pending_hash_scans(1, magnet_only=True):
            self.scan_hashes(limit=self.context.config.get("rss.scan_limit", 200))

    def _forget_widget(self, w):
        for i, x in enumerate(self._widgets):
            if x is w:
                del self._widgets[i]
                return

    def create_home_widget(self, parent):
        w = _RssHomeWidget(self, parent)
        self._widgets.append(w)
        w.destroyed.connect(lambda *_: self._forget_widget(w))
        return w

    def create_page(self, parent):
        w = _RssPageWidget(self, parent)
        self._widgets.append(w)
        w.destroyed.connect(lambda *_: self._forget_widget(w))
        return w


class _Fetcher(QtCore.QObject):
    finished = QtCore.Signal(list)
    item_added = QtCore.Signal(dict)
    feed_done = QtCore.Signal(dict)

    def __init__(self, feeds, store, proxy="", retry_count=3, retry_delay=5, max_workers=4):
        super().__init__()
        self.feeds = feeds
        self.store = store
        self.proxy = proxy
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.max_workers = max(1, int(max_workers) if max_workers else 4)
        self._lock = threading.RLock()

    def _final_tags(self, f):
        if f.get("tags"):
            return [t for t in f["tags"] if t]
        tags = self.store.get_feed_tags(f["id"])
        if tags:
            return tags
        return [f["tag"] or f["name"]]

    def _final_tag(self, f, e):
        if e.get("extra_tag"):
            return e["extra_tag"]
        return (self._final_tags(f) or [f["name"]])[0]

    def _process_feed(self, f):
        """抓取单个源并入库，返回结果 dict。在 worker 线程调用。"""
        from core.perf import timed
        try:
            with timed(f"rss.fetch.{f.get('name', 'feeds')}"):
                if f.get("feed_type") == "scrape":
                    opts = json.loads(f.get("scrape_options") or "{}")
                    rendered = bool(f.get("rendered"))
                    entries = scrape_page(
                        f["url"], opts,
                        proxy=self.proxy,
                        timeout=15,
                        custom_headers=json.loads(f.get("custom_headers", "{}")),
                        retry_count=self.retry_count,
                        retry_delay=self.retry_delay,
                        rendered=rendered,
                    )
                    etag = None
                    last_modified = None
                else:
                    logger.debug("开始抓取: %s (%s)", f["name"], f["url"])
                    entries, _feed_title, etag, last_modified = fetch_feed(
                        f["url"],
                        proxy=self.proxy,
                        custom_headers=json.loads(f.get("custom_headers", "{}")),
                        etag=f.get("etag") or None,
                        last_modified=f.get("last_modified") or None,
                        retry_count=self.retry_count,
                        retry_delay=self.retry_delay,
                    )
                    if not entries and etag:
                        logger.debug("304 无更新: %s", f["name"])
                        self.store.update_feed_refresh_time(f["id"])
                        return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": ""}

            entries = self.store.apply_filter_rules(entries)
            entries = [e for e in entries if not e.get("_skip")]
            for e in entries:
                e["_final_tag"] = self._final_tag(f, e)
            with self._lock:
                added = self.store.ingest(self._final_tags(f), entries, feed_id=f["id"])
            self.store.update_feed_refresh_time(f["id"])
            if etag is not None:
                self.store.update_feed(f["id"], etag=etag or "", last_modified=last_modified or "")
            self.store.clear_feed_error(f["id"])
            # 自动检测该源是否为磁力/种子源（返回结果里带 hash/磁链/种子）
            if any((e.get("torrent_hash") or extract_btih(e.get("link", "")))
                   for e in entries):
                self.store.set_feed_is_torrent(f["id"], 1)
            logger.info("抓取完成: %s — %d条, 新增%d条", f["name"], len(entries), added)
            for e in entries:
                if added > 0:
                    matched_kw = self.store.check_keywords(e.get("title", ""), e.get("description", ""))
                    if matched_kw:
                        self.item_added.emit(
                            {
                                "title": e.get("title", ""),
                                "link": e.get("link", ""),
                                "source": f["name"],
                                "keywords": [kw["keyword"] for kw in matched_kw],
                            }
                        )
            return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": len(entries), "added": added, "error": ""}
        except Exception as ex:
            logger.warning("抓取失败: %s — %s", f["name"], ex)
            self.store.set_feed_error(f["id"], str(ex))
            return {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": str(ex)}

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        counts = []

        def work(f):
            r = self._process_feed(f)
            r = r or {"feed_id": f["id"], "name": f["name"], "tag": f["tag"], "total": 0, "added": 0, "error": ""}
            self.feed_done.emit(r)
            return (r.get("name", ""), r.get("tag", ""), r.get("total", 0), r.get("added", 0))

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            counts = list(ex.map(work, self.feeds))
        self.finished.emit(counts)


_TORRENT_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']*(?:magnet:|\.torrent|urn:btih:)[^"\']*)["\']', re.IGNORECASE)
_MAGNET_BARE_RE = re.compile(r'magnet:\?[^\s"\'<>]+', re.IGNORECASE)


class _HashScanner(QtCore.QObject):
    """后台、限速的磁链/种子 hash 解析器：抓取无 hash 条目的原文页检索磁力/种子链接并缓存。"""
    done = QtCore.Signal(int)

    def __init__(self, store, proxy="", retry_count=1, retry_delay=2, rate_limit_ms=1000):
        super().__init__()
        self.store = store
        self.proxy = proxy
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.rate_limit_ms = max(50, rate_limit_ms or 1000)

    def _fetch_links(self, url):
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        try:
            resp = requests.get(url, timeout=12, headers=headers, proxies=proxies, verify=False)
            resp.raise_for_status()
            html = resp.text or ""
        except Exception:
            return []
        found = []
        for m in _TORRENT_HREF_RE.finditer(html):
            u = m.group(1).strip()
            if u and u not in found:
                found.append(u)
        for m in _MAGNET_BARE_RE.finditer(html):
            u = m.group(0).strip()
            if u and u not in found:
                found.append(u)
        # 补齐相对 .torrent 链接
        from urllib.parse import urljoin
        resolved = []
        for u in found:
            if u.startswith("/") and not (u.startswith("magnet:")):
                u = urljoin(url, u)
            resolved.append(u)
        return resolved

    def run(self, limit=200, magnet_only=True):
        import time
        pending = self.store.get_pending_hash_scans(limit, magnet_only=magnet_only)
        if not pending:
            self.done.emit(0)
            return
        self.store.mark_hash_scan([p["hash"] for p in pending], 1)
        scanned = 0
        for idx, p in enumerate(pending):
            if idx > 0:
                time.sleep(self.rate_limit_ms / 1000.0)
            link = p.get("link") or ""
            if _is_magnet_or_torrent(link):
                # 链接自带磁力/种子：直接并入（hash 由 record 提取）
                links = [link] if link else []
            else:
                links = self._fetch_links(link)
            if links:
                self.store.record_item_torrent_links(p["hash"], links)
                scanned += 1
            else:
                self.store.mark_hash_scan([p["hash"]], 3)
        self.done.emit(scanned)


def _btn_style(min_width=70, padding="6px 16px", radius=8, font_size=13):
    """主题感知的次级按钮样式：半透明面板 + 细边框，支持 hover/checked 态。"""
    c = _rss_colors()
    return (
        "QPushButton {{ padding: {padding}; border: 1px solid {control_border}; border-radius: {radius}px; "
        "background: {control_bg}; color: {text}; font-size: {font_size}px; "
        "min-width: {min_width}px; min-height: 20px; }}"
        "QPushButton:hover {{ background: {control_bg_hover}; border-color: {control_border_hover}; }}"
        "QPushButton:pressed {{ background: rgba(0,0,0,0.10); }}"
        "QPushButton:checked {{ background: {accent_bg}; border-color: {accent}; color: {accent}; }}"
        "QPushButton:disabled {{ color: {text_faint}; background: transparent; border-color: {border}; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _btn_primary_style(min_width=70, padding="6px 16px", radius=8, font_size=13):
    """主题感知的主强调按钮样式：实心强调色，hover/pressed 加深。"""
    c = _rss_colors()
    return (
        "QPushButton {{ padding: {padding}; border: none; border-radius: {radius}px; "
        "background: {accent}; color: #ffffff; font-size: {font_size}px; font-weight: bold; "
        "min-width: {min_width}px; min-height: 20px; }}"
        "QPushButton:hover {{ background: {accent_hover}; }}"
        "QPushButton:pressed {{ background: {accent_pressed}; }}"
        "QPushButton:disabled {{ background: {text_faint}; color: #aaaaaa; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _sidebar_qss():
    """主题感知的侧边栏列表样式：圆角条目 + hover/选中高亮。"""
    c = _rss_colors()
    return (
        "QListWidget {{ background: {panel}; border-right: 1px solid {border}; "
        "font-size: 12px; border-top: none; border-left: none; border-bottom: none; }}"
        "QListWidget::item {{ height: 28px; padding-left: 8px; margin: 1px 4px; border-radius: 6px; }}"
        "QListWidget::item:hover {{ background: {row_hover}; }}"
        "QListWidget::item:selected {{ background: {row_selected}; color: {title_unread}; }}"
        "QListWidget::item:selected:hover {{ background: {row_selected}; }}"
        "QPushButton {{ font-size: 12px; padding: 4px 10px; }}"
    ).format(**c)


def _bind_geometry(dialog, key, default_size=None):
    """为对话框绑定几何记忆：启动恢复、关闭保存。"""
    from core.ui_state import window_geometry
    geometry = window_geometry()
    geometry.apply(dialog, key, default_size=default_size)
    dialog.finished.connect(lambda *_: geometry.capture(dialog, key))


def _decode_feed_icon(icon_data):
    """把 feeds.icon 的 base64 串转成 QIcon；无法解码返回 None。"""
    import base64
    if not icon_data:
        return None
    if icon_data.startswith("base64:"):
        icon_data = icon_data[len("base64:"):]
    try:
        raw = base64.b64decode(icon_data)
    except Exception:
        return None
    pixmap = QtGui.QPixmap()
    if pixmap.loadFromData(raw):
        return QtGui.QIcon(pixmap)
    return None


class _FaviconWorker(QtCore.QObject):
    """后台抓取订阅源 favicon 并写入 feeds.icon 缓存。"""
    done = QtCore.Signal()

    def __init__(self, store, proxy=""):
        super().__init__()
        self.store = store
        self.proxy = proxy

    def run(self):
        import base64, requests
        from urllib.parse import urlparse
        feeds = self.store.feeds_needing_favicon()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        for f in feeds:
            url = f.get("url") or ""
            host = urlparse(url).netloc or "" if url else ""
            icon = ""
            candidates = [f"https://{host}/favicon.ico", f"https://www.google.com/s2/favicons?domain={host}"]
            for c in candidates:
                if not host and "google" not in c:
                    continue
                try:
                    r = requests.get(c, timeout=8, headers=headers, proxies=proxies, verify=False)
                    if r.status_code == 200 and r.content:
                        icon = "base64:" + base64.b64encode(r.content).decode()
                        break
                except Exception:
                    continue
            self.store.set_feed_icon(f["id"], icon)
        self.done.emit()


_TITLE_FONT_PX = 11


class _WrapRow(QtWidgets.QWidget):
    """可换行的标题行：内部用 word-wrap QLabel，自适应行高，可点击。"""

    clicked = QtCore.Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        self.label = QtWidgets.QLabel(text)
        self.label.setObjectName("rssTitleLabel")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        f = self.label.font()
        f.setPointSizeF(_TITLE_FONT_PX)
        self.label.setFont(f)
        lay.addWidget(self.label)
        self.label.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            obj is self.label
            and event.type() == QtCore.QEvent.MouseButtonRelease
            and event.button() == QtCore.Qt.LeftButton
        ):
            self.clicked.emit()
        return super().eventFilter(obj, event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def text(self):
        return self.label.text()

    def setText(self, text):
        self.label.setText(text)

    def setStyleSheet(self, ss):
        self.label.setStyleSheet(ss.replace("QPushButton", "QLabel"))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        m = self.layout().contentsMargins()
        avail = max(width - m.left() - m.right() - 4, 40)
        return self.label.heightForWidth(avail) + m.top() + m.bottom() + 2


class _HeadRow(QtWidgets.QWidget):
    """磁链聚合分组头：左侧可换行标题(▸ 前缀)，右侧固定"来源计数"徽标(不换行、样式参考标签)。"""

    titleClicked = QtCore.Signal()
    badgeClicked = QtCore.Signal()
    headDoubleClicked = QtCore.Signal()
    checkboxToggled = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)
        self.checkbox = QtWidgets.QCheckBox()
        lay.addWidget(self.checkbox)
        self.checkbox.toggled.connect(self.checkboxToggled)
        self.title_label = QtWidgets.QLabel("")
        self.title_label.setObjectName("rssHeadTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        f = self.title_label.font()
        f.setPointSizeF(_TITLE_FONT_PX)
        self.title_label.setFont(f)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("rssHeadCount")
        self.count_label.setWordWrap(False)
        self.count_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        self.count_label.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        lay.addWidget(self.title_label, 1)
        lay.addWidget(self.count_label, 0)
        self.title_label.installEventFilter(self)
        self.count_label.installEventFilter(self)

    def set_check_state(self, state):
        self.checkbox.blockSignals(True)
        self.checkbox.setCheckState(state)
        self.checkbox.blockSignals(False)

    def check_state(self):
        return self.checkbox.checkState()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            if obj in (self.title_label, self.count_label):
                self.headDoubleClicked.emit()
                return True
        if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if obj is self.count_label:
                self.badgeClicked.emit()
                return True
            if obj is self.title_label:
                self.titleClicked.emit()
                return True
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.headDoubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def setText(self, text):
        self.title_label.setText(text)

    def text(self):
        return self.title_label.text()

    def set_count(self, text):
        self.count_label.setText(text)

    def setStyleSheet(self, ss):
        """ss 用 QPushButton#id 书写；转换为 QLabel 选择器后按 objectName 分派，合并同一标签的基础与 :hover 规则。"""
        rules = {"#rssHeadTitle": [], "#rssHeadCount": []}
        for block in ss.split("}"):
            if "{" not in block:
                continue
            head, body = block.split("{", 1)
            sel = head.strip()
            if "#rssHeadTitle" in sel:
                rules["#rssHeadTitle"].append(sel.replace("QPushButton", "QLabel") + "{" + body + "}")
            elif "#rssHeadCount" in sel:
                rules["#rssHeadCount"].append(sel.replace("QPushButton", "QLabel") + "{" + body + "}")
        if rules["#rssHeadTitle"]:
            self.title_label.setStyleSheet("".join(rules["#rssHeadTitle"]))
        if rules["#rssHeadCount"]:
            self.count_label.setStyleSheet("".join(rules["#rssHeadCount"]))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        m = self.layout().contentsMargins()
        spawn = (self.checkbox.sizeHint().width() + self.layout().spacing()
                 + self.count_label.sizeHint().width() + self.layout().spacing())
        avail = max(width - m.left() - m.right() - spawn, 40)
        return self.title_label.heightForWidth(avail) + m.top() + m.bottom() + 2


class _AutoRow(QtWidgets.QWidget):
    """列表条目行容器：把行高交给内部标题自适应（按可用宽度换行）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._title = None

    def bind_title(self, title_widget):
        self._title = title_widget

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if self._title is None:
            return max(self.sizeHint().height(), 24)
        spacer = 4
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i).widget()
            if w is not None and w is not self._title:
                spacer += w.sizeHint().width() + self.layout().spacing()
        return self._title.heightForWidth(max(width - spacer, 40))


def _pill_style(bg, fg):
    """标签/类型药丸样式：圆角胶囊 + 对比色前景。"""
    return (
        f"QLabel {{ background: {bg}; color: {fg}; padding: 2px 9px; "
        "border-radius: 9px; font-size: 12px; font-weight: 600; }"
    )


def _make_item_row(widget, it, on_open, checked=False):
    c = _rss_colors()
    tags = it["tags"] or ""
    is_read = bool(it.get("read"))
    is_fav = bool(it.get("favorite"))
    type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"

    row_widget = _AutoRow()
    row_layout = QtWidgets.QHBoxLayout(row_widget)
    row_layout.setContentsMargins(4, 2, 4, 2)
    row_layout.setSpacing(6)

    chk = QtWidgets.QCheckBox()
    chk.setChecked(checked)
    row_layout.addWidget(chk)

    # 未读圆点：未读高亮，已读淡出
    dot = QtWidgets.QLabel("●")
    dot.setFixedWidth(10)
    dot.setStyleSheet(
        f"QLabel {{ color: {c['dot_unread'] if not is_read else c['dot_read']}; "
        "font-size: 10px; }")
    row_layout.addWidget(dot)

    if is_fav:
        fav_label = QtWidgets.QLabel("★")
        fav_label.setStyleSheet(f"QLabel {{ color: {c['fav_color']}; font-size: 14px; }}")
        fav_label.setFixedWidth(16)
        row_layout.addWidget(fav_label)

    title_text = it["title"] or it["link"]
    title_btn = _WrapRow(title_text)
    if is_read:
        title_btn.setStyleSheet(
            f"QLabel {{ text-align: left; border: none; background: transparent; "
            f"color: {c['title_read']}; padding: 2px; }}"
            f"QLabel:hover {{ color: {c['text_secondary']}; }}"
        )
    else:
        title_btn.setStyleSheet(
            f"QLabel {{ text-align: left; border: none; background: transparent; color: {c['title_unread']}; "
            "font-weight: 600; padding: 2px; }"
            f"QLabel:hover {{ color: {c['accent']}; }}"
        )
    title_btn._rss_dot = dot
    title_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    row_layout.addWidget(title_btn, 1)

    if tags:
        tag_label = QtWidgets.QLabel(tags)
        tag_label.setStyleSheet(_pill_style(c["pill_tag_bg"], c["pill_tag_fg"]))
        tag_label.setAlignment(QtCore.Qt.AlignCenter)
        row_layout.addWidget(tag_label)

    type_label = QtWidgets.QLabel(type_tag)
    if type_tag == "磁链":
        type_label.setStyleSheet(_pill_style(c["pill_torrent_bg"], c["pill_torrent_fg"]))
    else:
        type_label.setStyleSheet(_pill_style(c["pill_article_bg"], c["pill_article_fg"]))
    type_label.setAlignment(QtCore.Qt.AlignCenter)
    row_layout.addWidget(type_label)

    pub = (it.get("published") or "").strip()
    if len(pub) >= 16:
        pub = pub[5:16]
    elif not pub:
        pub = ""
    if pub:
        time_label = QtWidgets.QLabel(pub)
        time_label.setStyleSheet(
            f"QLabel {{ color: {c['text_faint']}; font-size: 12px; padding-right: 4px; }}")
        time_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        row_layout.addWidget(time_label)

    row_widget.bind_title(title_btn)
    return row_widget, title_btn, chk


class _EditFeedDialog(QtWidgets.QDialog):
    def __init__(self, feed, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑订阅源")
        self.setMinimumWidth(450)
        _bind_geometry(self, "rss_edit_feed")
        self.feed = feed
        self.store = store

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit(feed.get("name", ""))
        self.in_url = QtWidgets.QLineEdit(feed.get("url", ""))
        feed_tags = feed.get("tags") or ([feed.get("tag")] if feed.get("tag") else [])
        self.in_tag = QtWidgets.QLineEdit(", ".join(t for t in feed_tags if t))
        self.in_tag.setPlaceholderText("多个标签用逗号分隔，例如：科技, 资讯")
        self.in_group = QtWidgets.QLineEdit(feed.get("group_name", ""))
        self.in_interval = QtWidgets.QSpinBox()
        self.in_interval.setRange(60, 86400)
        self.in_interval.setSingleStep(60)
        self.in_interval.setValue(feed.get("refresh_interval", 1800))
        self.in_interval.setSuffix(" 秒")
        form.addRow("名称", self.in_name)
        form.addRow("URL", self.in_url)
        form.addRow("标签", self.in_tag)
        form.addRow("分组", self.in_group)
        form.addRow("刷新间隔", self.in_interval)
        lay.addLayout(form)

        if feed.get("last_error"):
            err_label = QtWidgets.QLabel(f"错误: {feed['last_error']}")
            err_label.setStyleSheet("QLabel { color: red; }")
            lay.addWidget(err_label)

        if feed.get("feed_type") == "scrape":
            self._scrape_options = json.loads(feed.get("scrape_options") or "{}")
            self.chk_rendered = QtWidgets.QCheckBox("需要 JS 渲染时才抓取（动态网页较慢）")
            self.chk_rendered.setChecked(bool(feed.get("rendered")))
            lay.addWidget(self.chk_rendered)
            sel_row = QtWidgets.QHBoxLayout()
            self.btn_selector = QtWidgets.QPushButton("重新选择元素")
            self.btn_selector.setStyleSheet(_btn_primary_style())
            self.btn_selector.clicked.connect(self._open_selector)
            sel_row.addWidget(self.btn_selector)
            self.lb_scrape = QtWidgets.QLabel(self._scrape_label())
            self.lb_scrape.setWordWrap(True)
            self.lb_scrape.setStyleSheet(f"color:{_rss_colors()['accent']};")
            sel_row.addWidget(self.lb_scrape, 1)
            lay.addLayout(sel_row)

            kw_row = QtWidgets.QHBoxLayout()
            kw_row.addWidget(QtWidgets.QLabel("关键词过滤"))
            self.in_keywords = QtWidgets.QLineEdit()
            self.in_keywords.setPlaceholderText("逗号/空格分隔，命中任一即保留；留空=接受全部")
            self.in_keywords.setClearButtonEnabled(True)
            kw_row.addWidget(self.in_keywords, 1)
            lay.addLayout(kw_row)
            kws = (self._scrape_options or {}).get("keywords") or []
            self.in_keywords.setText(", ".join(kws))
        else:
            self._scrape_options = None

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("保存")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _scrape_label(self):
        sel = (self._scrape_options or {}).get("selector", "")
        mode = "列表" if (self._scrape_options or {}).get("mode") == "list" else "单元素"
        return f"[{mode}] {sel}"

    def _open_selector(self):
        from .page_selector import PageSelectorDialog
        dlg = PageSelectorDialog(self.feed.get("url", ""), self, initial_options=self._scrape_options)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._scrape_options = dlg.options()
            self.lb_scrape.setText(self._scrape_label())

    def _do_save(self):
        name = self.in_name.text().strip()
        url = self.in_url.text().strip()
        feed_tags = [t.strip() for t in self.in_tag.text().replace("，", ",").split(",") if t.strip()] or [name]
        tag = feed_tags[0]
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        kwargs = dict(name=name, url=url, tag=tag, tags=feed_tags, group_name=group, refresh_interval=interval)
        if self.feed.get("feed_type") == "scrape":
            if not (self._scrape_options or {}).get("selector"):
                QtWidgets.QMessageBox.warning(self, "提示", "请先用页面选择器锁定要监控的元素")
                return
            opts = dict(self._scrape_options)
            opts["keywords"] = _parse_keywords(self.in_keywords.text())
            kwargs["scrape_options"] = opts
            kwargs["rendered"] = 1 if self.chk_rendered.isChecked() else 0
        self.store.update_feed(self.feed["id"], **kwargs)
        self.accept()


class _AddFeedDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加订阅源")
        self.setMinimumWidth(480)
        _bind_geometry(self, "rss_add_feed")
        self.owner = owner
        self._scrape_options = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("类型"))
        self.combo_type = QtWidgets.QComboBox()
        self.combo_type.addItem("标准 RSS / Atom", "normal")
        self.combo_type.addItem("页面监控（网页元素）", "scrape")
        self.combo_type.currentIndexChanged.connect(self._toggle_type)
        type_row.addWidget(self.combo_type, 1)
        lay.addLayout(type_row)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("例如：阮一峰博客 / 某页面价格监控")
        self.in_url = QtWidgets.QLineEdit()
        self.in_url.setPlaceholderText("RSS/Atom feed 地址，或要监控的网页 URL")
        self.in_tag = QtWidgets.QLineEdit()
        self.in_tag.setPlaceholderText("多个标签用逗号分隔，例如：科技, 资讯（可选，默认同名称）")
        self.in_group = QtWidgets.QLineEdit()
        self.in_group.setPlaceholderText("分组（可选）")
        self.in_interval = QtWidgets.QSpinBox()
        self.in_interval.setRange(60, 86400)
        self.in_interval.setSingleStep(60)
        self.in_interval.setValue(1800)
        self.in_interval.setSuffix(" 秒")
        self.in_interval.setSpecialValueText("自定义")
        form.addRow("名称", self.in_name)
        form.addRow("URL", self.in_url)
        form.addRow("标签", self.in_tag)
        form.addRow("分组", self.in_group)
        form.addRow("刷新间隔", self.in_interval)
        lay.addLayout(form)

        # 标准 RSS：自动发现
        self.btn_discover = QtWidgets.QPushButton("自动发现RSS")
        self.btn_discover.clicked.connect(self._discover)
        lay.addWidget(self.btn_discover)

        # 页面监控：选择器
        self.scrape_box = QtWidgets.QWidget()
        scrape_lay = QtWidgets.QVBoxLayout(self.scrape_box)
        scrape_lay.setContentsMargins(0, 0, 0, 0)
        scrape_lay.setSpacing(8)
        row_sel = QtWidgets.QHBoxLayout()
        self.btn_selector = QtWidgets.QPushButton("打开页面选择器")
        self.btn_selector.setStyleSheet(_btn_primary_style())
        self.btn_selector.clicked.connect(self._open_selector)
        row_sel.addWidget(self.btn_selector)
        self.lb_scrape = QtWidgets.QLabel("点击按钮打开页面，用鼠标点选要监控的元素。")
        self.lb_scrape.setWordWrap(True)
        self.lb_scrape.setStyleSheet(f"color:{_rss_colors()['text_secondary']};")
        row_sel.addWidget(self.lb_scrape, 1)
        scrape_lay.addLayout(row_sel)

        self.chk_rendered = QtWidgets.QCheckBox("需要 JS 渲染时才抓取（动态网页较慢）")
        scrape_lay.addWidget(self.chk_rendered)

        kw_row = QtWidgets.QHBoxLayout()
        kw_row.addWidget(QtWidgets.QLabel("关键词过滤"))
        self.in_keywords = QtWidgets.QLineEdit()
        self.in_keywords.setPlaceholderText("逗号/空格分隔，命中任一即保留；留空=接受全部")
        self.in_keywords.setClearButtonEnabled(True)
        kw_row.addWidget(self.in_keywords, 1)
        scrape_lay.addLayout(kw_row)

        self.scrape_box.setVisible(False)
        lay.addWidget(self.scrape_box)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _toggle_type(self):
        is_scrape = self.combo_type.currentData() == "scrape"
        self.btn_discover.setVisible(not is_scrape)
        self.scrape_box.setVisible(is_scrape)

    def _open_selector(self):
        url = self.in_url.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "提示", "请先填写要监控的网页 URL")
            return
        from .page_selector import PageSelectorDialog
        dlg = PageSelectorDialog(url, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            opts = dlg.options()
            self._scrape_options = opts
            sel = opts.get("selector", "")
            mode = "列表" if opts.get("mode") == "list" else "单元素"
            self.lb_scrape.setText(f"已锁定: [{mode}] {sel}")

    def _discover(self):
        url = self.in_url.text().strip()
        if not url:
            return
        feeds = self.owner.store.discover_feed(url)
        if not feeds:
            QtWidgets.QMessageBox.information(self, "发现", "未找到RSS订阅源")
            return
        if len(feeds) == 1:
            self.in_url.setText(feeds[0]["href"])
            if feeds[0].get("title") and not self.in_name.text():
                self.in_name.setText(feeds[0]["title"])
        else:
            items = [f"{f['title'] or f['href']} ({f['type']})" for f in feeds]
            item, ok = QtWidgets.QInputDialog.getItem(self, "选择订阅源", "发现多个订阅源:", items, 0, False)
            if ok:
                idx = items.index(item)
                self.in_url.setText(feeds[idx]["href"])
                if feeds[idx].get("title") and not self.in_name.text():
                    self.in_name.setText(feeds[idx]["title"])

    def _do_add(self):
        name = self.in_name.text().strip()
        url = self.in_url.text().strip()
        feed_tags = [t.strip() for t in self.in_tag.text().replace("，", ",").split(",") if t.strip()] or [name]
        tag = feed_tags[0]
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        if self.combo_type.currentData() == "scrape":
            if not self._scrape_options or not self._scrape_options.get("selector"):
                QtWidgets.QMessageBox.warning(self, "提示", "请先用页面选择器锁定要监控的元素")
                return
            opts = dict(self._scrape_options)
            opts["keywords"] = _parse_keywords(self.in_keywords.text())
            self.owner.store.add_feed(
                name, url, tag, group, interval,
                feed_type="scrape",
                scrape_options=opts,
                rendered=1 if self.chk_rendered.isChecked() else 0,
                tags=feed_tags,
            )
        else:
            self.owner.store.add_feed(name, url, tag, group, interval, tags=feed_tags)
        self.accept()


class _FeedManageDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理订阅源")
        self.setMinimumSize(600, 400)
        _bind_geometry(self, "rss_feed_manage", default_size=(600, 400))
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self.feed_list = QtWidgets.QListWidget()
        self.feed_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.feed_list.model().rowsMoved.connect(self._on_feed_order_changed)
        lay.addWidget(self.feed_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("添加订阅")
        btn_add.setStyleSheet(_btn_primary_style())
        btn_add.clicked.connect(self._show_add_dialog)
        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.setStyleSheet(_btn_style())
        btn_edit.clicked.connect(self._edit_feed)
        btn_del = QtWidgets.QPushButton("删除选中")
        btn_del.setStyleSheet(_btn_style())
        btn_del.clicked.connect(self._remove_feed)
        btn_toggle = QtWidgets.QPushButton("启用/停用")
        btn_toggle.setStyleSheet(_btn_style())
        btn_toggle.clicked.connect(self._toggle_feed)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_toggle)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self._load_feeds()

    def _load_feeds(self):
        self.feed_list.clear()
        for f in self.owner.store.list_feeds():
            status = "✓" if f["enabled"] else "✗"
            group = f" [{f['group_name']}]" if f.get("group_name") else ""
            error = f" ⚠{f['last_error'][:30]}" if f.get("last_error") else ""
            kind = " [监控]" if f.get("feed_type") == "scrape" else ""
            text = "{}{} {}{}{} — {}{}".format(status, kind, f["name"], group, "", f["url"], error)
            tags = f.get("tags") or ([f["tag"]] if f.get("tag") else [])
            tags = [t for t in tags if t and t != f["name"]]
            if tags:
                text += "  (标签: {})".format(", ".join(tags))
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, f["id"])
            item.setData(QtCore.Qt.UserRole + 1, f["enabled"])
            self.feed_list.addItem(item)

    def _on_feed_order_changed(self):
        feed_ids = []
        for i in range(self.feed_list.count()):
            item = self.feed_list.item(i)
            feed_ids.append(item.data(QtCore.Qt.UserRole))
        self.owner.store.update_feed_order(feed_ids)

    def _show_add_dialog(self):
        dlg = _AddFeedDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _edit_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        feed = self.owner.store.get_feed_by_id(fid)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _remove_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_feed(fid)
        self._load_feeds()

    def _toggle_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        enabled = item.data(QtCore.Qt.UserRole + 1)
        self.owner.store.set_feed_enabled(fid, not enabled)
        self._load_feeds()


class _SettingsDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RSS 设置")
        self.setMinimumSize(500, 600)
        _bind_geometry(self, "rss_settings", default_size=(500, 600))
        self.owner = owner
        self._apply_dialog_theme()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QtWidgets.QWidget()
        content.setAutoFillBackground(False)
        content.setObjectName("rssSettingsContent")
        content.setStyleSheet("QWidget#rssSettingsContent { background: transparent; }")
        lay = QtWidgets.QVBoxLayout(content)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        settings_group = QtWidgets.QGroupBox("代理设置")
        settings_lay = QtWidgets.QFormLayout(settings_group)
        self.in_proxy = QtWidgets.QLineEdit()
        self.in_proxy.setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self.in_proxy.setText(self.owner.context.config.get("rss.proxy", ""))
        settings_lay.addRow("代理地址", self.in_proxy)
        lay.addWidget(settings_group)

        cleanup_group = QtWidgets.QGroupBox("数据清理")
        cleanup_lay = QtWidgets.QHBoxLayout(cleanup_group)
        cleanup_lay.addWidget(QtWidgets.QLabel("清理"))
        self.spin_cleanup_days = QtWidgets.QSpinBox()
        self.spin_cleanup_days.setRange(7, 365)
        self.spin_cleanup_days.setValue(self.owner.context.config.get("rss.cleanup_days", 30))
        self.spin_cleanup_days.setSuffix(" 天前的数据")
        cleanup_lay.addWidget(self.spin_cleanup_days)
        btn_cleanup = QtWidgets.QPushButton("清理")
        btn_cleanup.setStyleSheet(_btn_primary_style())
        btn_cleanup.clicked.connect(self._cleanup_old)
        cleanup_lay.addWidget(btn_cleanup)
        lay.addWidget(cleanup_group)

        notify_group = QtWidgets.QGroupBox("通知设置")
        notify_lay = QtWidgets.QFormLayout(notify_group)
        self.chk_notify = QtWidgets.QCheckBox("启用桌面通知")
        self.chk_notify.setChecked(self.owner.context.config.get("rss.notification_enabled", True))
        self.chk_notify.stateChanged.connect(lambda s: self.owner.context.config.set("rss.notification_enabled", s == QtCore.Qt.CheckState.Checked.value))
        notify_lay.addRow(self.chk_notify)
        lay.addWidget(notify_group)

        categories_group = QtWidgets.QGroupBox("分类管理")
        categories_lay = QtWidgets.QVBoxLayout(categories_group)
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setMaximumHeight(100)
        categories_lay.addWidget(self.category_list)
        cat_btn_row = QtWidgets.QHBoxLayout()
        btn_add_cat = QtWidgets.QPushButton("添加分类")
        btn_add_cat.setStyleSheet(_btn_style())
        btn_add_cat.clicked.connect(self._show_category_dialog)
        btn_edit_cat = QtWidgets.QPushButton("编辑")
        btn_edit_cat.setStyleSheet(_btn_style())
        btn_edit_cat.clicked.connect(self._edit_category)
        btn_del_cat = QtWidgets.QPushButton("删除")
        btn_del_cat.setStyleSheet(_btn_style())
        btn_del_cat.clicked.connect(self._remove_category)
        cat_btn_row.addWidget(btn_add_cat)
        cat_btn_row.addWidget(btn_edit_cat)
        cat_btn_row.addWidget(btn_del_cat)
        cat_btn_row.addStretch(1)
        categories_lay.addLayout(cat_btn_row)
        lay.addWidget(categories_group)

        keywords_group = QtWidgets.QGroupBox("关键词提醒")
        keywords_lay = QtWidgets.QVBoxLayout(keywords_group)
        self.keyword_list = QtWidgets.QListWidget()
        self.keyword_list.setMaximumHeight(100)
        keywords_lay.addWidget(self.keyword_list)
        kw_btn_row = QtWidgets.QHBoxLayout()
        btn_add_kw = QtWidgets.QPushButton("添加关键词")
        btn_add_kw.setStyleSheet(_btn_style())
        btn_add_kw.clicked.connect(self._show_keyword_dialog)
        btn_del_kw = QtWidgets.QPushButton("删除选中")
        btn_del_kw.setStyleSheet(_btn_style())
        btn_del_kw.clicked.connect(self._remove_keyword)
        kw_btn_row.addWidget(btn_add_kw)
        kw_btn_row.addWidget(btn_del_kw)
        kw_btn_row.addStretch(1)
        keywords_lay.addLayout(kw_btn_row)
        lay.addWidget(keywords_group)

        rules_group = QtWidgets.QGroupBox("过滤规则")
        rules_lay = QtWidgets.QVBoxLayout(rules_group)
        self.rule_list = QtWidgets.QListWidget()
        self.rule_list.setMaximumHeight(100)
        rules_lay.addWidget(self.rule_list)
        rule_btn_row = QtWidgets.QHBoxLayout()
        btn_add_rule = QtWidgets.QPushButton("添加规则")
        btn_add_rule.setStyleSheet(_btn_style())
        btn_add_rule.clicked.connect(self._show_filter_dialog)
        btn_del_rule = QtWidgets.QPushButton("删除选中")
        btn_del_rule.setStyleSheet(_btn_style())
        btn_del_rule.clicked.connect(self._remove_rule)
        btn_toggle_rule = QtWidgets.QPushButton("启用/禁用")
        btn_toggle_rule.setStyleSheet(_btn_style())
        btn_toggle_rule.clicked.connect(self._toggle_rule)
        rule_btn_row.addWidget(btn_add_rule)
        rule_btn_row.addWidget(btn_del_rule)
        rule_btn_row.addWidget(btn_toggle_rule)
        rule_btn_row.addStretch(1)
        rules_lay.addLayout(rule_btn_row)
        lay.addWidget(rules_group)

        history_group = QtWidgets.QGroupBox("阅读历史")
        history_lay = QtWidgets.QVBoxLayout(history_group)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setMaximumHeight(120)
        history_lay.addWidget(self.history_list)
        btn_refresh_history = QtWidgets.QPushButton("刷新历史")
        btn_refresh_history.setStyleSheet(_btn_style())
        btn_refresh_history.clicked.connect(self._load_history)
        history_lay.addWidget(btn_refresh_history)
        lay.addWidget(history_group)

        stats_group = QtWidgets.QGroupBox("统计信息")
        stats_lay = QtWidgets.QVBoxLayout(stats_group)
        self.lb_stats = QtWidgets.QLabel("")
        stats_lay.addWidget(self.lb_stats)
        btn_refresh_stats = QtWidgets.QPushButton("刷新统计")
        btn_refresh_stats.setStyleSheet(_btn_style())
        btn_refresh_stats.clicked.connect(self._load_stats)
        stats_lay.addWidget(btn_refresh_stats)
        lay.addWidget(stats_group)

        lay.addStretch(1)
        scroll.setWidget(content)
        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.addWidget(scroll)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_save = QtWidgets.QPushButton("保存设置")
        btn_save.setStyleSheet(_btn_primary_style())
        btn_save.clicked.connect(self._save_settings)
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.setStyleSheet(_btn_style())
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        btn_row.addWidget(btn_save)
        main_lay.addLayout(btn_row)

        self._load_keywords()
        self._load_rules()
        self._load_stats()
        self._load_categories()
        self._load_history()

    def _save_settings(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner.set_proxy(proxy)
        self.owner.context.config.set("rss.cleanup_days", self.spin_cleanup_days.value())
        self.accept()

    def _apply_dialog_theme(self):
        # 与其他页面/对话框一致：不覆盖全局 QFluentWidgets 主题/QSS，
        # 让 QGroupBox/QSpinBox/QLineEdit 跟应用主题渲染；不使用壁纸，保持普通面板风格。
        self.setStyleSheet("")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.store.cleanup_old(days)
        self.owner.context.config.set("rss.cleanup_days", days)
        QtWidgets.QMessageBox.information(self, "清理", f"已清理 {days} 天前的数据")

    def _load_categories(self):
        self.category_list.clear()
        for c in self.owner.store.get_categories():
            self.category_list.addItem(f"{c['name']} ({c['color']})")

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            dlg = _CategoryDialog(self.owner, cats[idx], self)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            self.owner.store.remove_category(cats[idx]["id"])
            self._load_categories()

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            text = kw["keyword"]
            if kw.get("notify"):
                text += " 🔔"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if not item:
            return
        kid = item.data(QtCore.Qt.UserRole)
        if kid is None:
            return
        self.owner.store.remove_keyword(kid)
        self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for r in self.owner.store.get_filter_rules():
            status = "✓" if r.get("enabled") else "✗"
            text = f"{status} {r['name']}: {r['field']} {r['operator']} {r['value']} → {r['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, r["id"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_filter_rule(rid)
        self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        rules = self.owner.store.get_filter_rules()
        for r in rules:
            if r["id"] == rid:
                self.owner.store.update_filter_rule(rid, enabled=not r.get("enabled", True))
                break
        self._load_rules()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(limit=50):
            item = QtWidgets.QListWidgetItem(f"{h['title'][:50]} ({h['read_at']})")
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        feed_stats = self.owner.store.get_feed_stats()
        total = sum(s.get("total", 0) for s in feed_stats)
        unread = sum(s.get("unread", 0) for s in feed_stats)
        read = total - unread
        fav_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM favorites").fetchone()
            fav_count = row["cnt"] if row else 0
        today_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM items WHERE date(published) = date('now','localtime')"
            ).fetchone()
            today_count = row["cnt"] if row else 0
        self.lb_stats.setText(
            f"总条目: {total} | 已读: {read} | 未读: {unread} | 收藏: {fav_count} | 今日新增: {today_count}"
        )


class _FilterRuleDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加过滤规则")
        self.setMinimumWidth(400)
        _bind_geometry(self, "rss_filter_rule")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("规则名称")
        self.combo_field = QtWidgets.QComboBox()
        self.combo_field.addItems(["标题", "描述", "链接"])
        self.combo_operator = QtWidgets.QComboBox()
        self.combo_operator.addItems(["包含", "不包含", "等于", "开头是", "结尾是", "正则"])
        self.in_value = QtWidgets.QLineEdit()
        self.in_value.setPlaceholderText("匹配值")
        self.combo_action = QtWidgets.QComboBox()
        self.combo_action.addItems(["添加标签", "跳过", "高亮"])
        self.in_action_value = QtWidgets.QLineEdit()
        self.in_action_value.setPlaceholderText("标签名称（添加标签时填写）")
        form.addRow("名称", self.in_name)
        form.addRow("字段", self.combo_field)
        form.addRow("条件", self.combo_operator)
        form.addRow("值", self.in_value)
        form.addRow("动作", self.combo_action)
        form.addRow("动作值", self.in_action_value)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        name = self.in_name.text().strip()
        field_map = {"标题": "title", "描述": "description", "链接": "link"}
        op_map = {"包含": "contains", "不包含": "not_contains", "等于": "equals", "开头是": "starts_with", "结尾是": "ends_with", "正则": "regex"}
        action_map = {"添加标签": "tag", "跳过": "skip", "高亮": "highlight"}
        field = field_map.get(self.combo_field.currentText(), "title")
        operator = op_map.get(self.combo_operator.currentText(), "contains")
        value = self.in_value.text().strip()
        action = action_map.get(self.combo_action.currentText(), "tag")
        action_value = self.in_action_value.text().strip()
        if not name or not value:
            return
        self.owner.store.add_filter_rule(name, field, operator, value, action, action_value)
        self.accept()


class _KeywordDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加关键词")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_keyword")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_keyword = QtWidgets.QLineEdit()
        self.in_keyword.setPlaceholderText("关键词")
        self.in_color = QtWidgets.QLineEdit()
        self.in_color.setText("#ff6b6b")
        self.chk_notify = QtWidgets.QCheckBox("匹配时通知")
        self.chk_notify.setChecked(True)
        form.addRow("关键词", self.in_keyword)
        form.addRow("颜色", self.in_color)
        form.addRow("", self.chk_notify)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        keyword = self.in_keyword.text().strip()
        color = self.in_color.text().strip() or "#ff6b6b"
        notify = 1 if self.chk_notify.isChecked() else 0
        if not keyword:
            return
        self.owner.store.add_keyword(keyword, color, notify)
        self.accept()


class _CategoryDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None, category=None):
        super().__init__(parent)
        self.setWindowTitle("编辑分类" if category else "添加分类")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_category")
        self.owner = owner
        self.category = category

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit(category.get("name", "") if category else "")
        self.in_color = QtWidgets.QLineEdit(category.get("color", "#1a73e8") if category else "#1a73e8")
        form.addRow("名称", self.in_name)
        form.addRow("颜色", self.in_color)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("保存")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_save(self):
        name = self.in_name.text().strip()
        color = self.in_color.text().strip() or "#1a73e8"
        if not name:
            return
        if self.category:
            self.owner.store.update_category(self.category["id"], name=name, color=color)
        else:
            self.owner.store.add_category(name, color)
        self.accept()


class _RssHomeWidget(QtWidgets.QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        header = QtWidgets.QHBoxLayout()
        _lc = _rss_colors()
        qf = _qf()
        lb_home_icon = qf["IconWidget"](qf["FluentIcon"].GLOBE)
        lb_home_icon.setFixedSize(22, 22)
        lb_home_icon.setStyleSheet(f"background: {_lc['accent_bg']}; border-radius: 6px;")
        header.addWidget(lb_home_icon)
        lb_home_title = QtWidgets.QLabel("RSS 聚合")
        lb_home_title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {_lc['title_unread']};")
        header.addWidget(lb_home_title)
        header.addStretch(1)

        self.lb_unread = QtWidgets.QLabel("")
        self.lb_unread.setStyleSheet(f"QLabel {{ color: {_lc['accent']}; font-weight: bold; }}")
        header.addWidget(self.lb_unread)

        self.spin_limit = QtWidgets.QSpinBox()
        self.spin_limit.setRange(100, 1000000)
        self.spin_limit.setSingleStep(1000)
        self.spin_limit.setPrefix("显示上限: ")
        self.spin_limit.setSuffix(" 条")
        self.spin_limit.setValue(self.owner.context.config.get("rss.home_limit", 100000))
        self.spin_limit.valueChanged.connect(self._on_limit_changed)
        header.addWidget(self.spin_limit)
        lay.addLayout(header)

        filter_row = QtWidgets.QHBoxLayout()
        self.combo_filter = qf["ComboBox"]()
        self.combo_filter.addItem("全部", None)
        self.combo_filter.addItem("未读", "unread")
        self.combo_filter.addItem("收藏", "favorite")
        self.combo_filter.addItem("磁链", "__磁链__")
        self.combo_filter.addItem("文章", "__文章__")
        self.combo_filter.currentIndexChanged.connect(self._load_items)
        filter_row.addWidget(self.combo_filter)
        filter_row.addStretch(1)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._load_items)
        filter_row.addWidget(self.search_input)
        lay.addLayout(filter_row)

        self.lb_list = QtWidgets.QListWidget()
        self.lb_list.itemDoubleClicked.connect(self._open_item)
        self.lb_list.itemClicked.connect(self._mark_read)
        lay.addWidget(self.lb_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn = qf["PrimaryPushButton"]("立即刷新")
        self.btn.clicked.connect(owner.refresh_now)
        btn_row.addWidget(self.btn)

        self.btn_mark_all = qf["PushButton"]("全部已读")
        self.btn_mark_all.clicked.connect(self._mark_all_read)
        btn_row.addWidget(self.btn_mark_all)
        lay.addLayout(btn_row)

    def _on_limit_changed(self, val):
        self.owner.context.config.set("rss.home_limit", val)
        self._load_items()

    def on_refreshed(self, counts):
        self._load_items()

    def on_feed_done(self, info):
        self._load_items()

    def on_hash_scan_done(self, scanned):
        self._load_items()

    def on_favicons_loaded(self):
        self._load_items()

    def _load_items(self):
        query = self.search_input.text().strip()
        if query:
            items = self.owner.store.search(query, self.spin_limit.value())
        else:
            fav = self.combo_filter.currentData() == "favorite"
            unread = self.combo_filter.currentData() == "unread"
            tag = self.combo_filter.currentData() if self.combo_filter.currentData() not in ("favorite", "unread") else None
            items = self.owner.store.recent(self.spin_limit.value(), tag_filter=tag, favorites_only=fav, unread_only=unread)
        self.lb_list.clear()
        for it in items:
            tags = it["tags"] or ""
            type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"
            is_read = bool(it.get("read"))
            is_fav = bool(it.get("favorite"))
            prefix = "  " if is_read else ""
            fav_mark = "★ " if is_fav else ""
            text = "{}{}[{}] {} [{}]".format(prefix, fav_mark, tags, it["title"], type_tag)
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            if is_read:
                item.setForeground(QtGui.QColor(_rss_colors()["title_read"]))
            self.lb_list.addItem(item)
        unread = self.owner.store.get_unread_count()
        self.lb_unread.setText(f"未读: {unread}" if unread else "")

    def _mark_read(self, item):
        h = item.data(QtCore.Qt.UserRole)
        if h:
            self.owner.store.mark_read(h)
            item.setForeground(QtGui.QColor(_rss_colors()["title_read"]))

    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        if link:
            webbrowser.open(link)

    def _mark_all_read(self):
        self.owner.store.mark_all_read()
        self._load_items()


class _AddAggregationDialog(QtWidgets.QDialog):
    """新建/编辑手动聚合：勾选成员（订阅源/标签），选处理类型，配置关键词三桶。"""

    TYPE_LABELS = {"mixed": "混合", "keyword": "关键词", "torrent": "磁链 Hash"}

    def __init__(self, owner, page, agg_id=None, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.page = page
        self.store = owner.store
        self.agg_id = agg_id
        self.agg = self.store.get_aggregation(agg_id) if agg_id else None
        self.setWindowTitle("编辑聚合" if self.agg else "新建聚合")
        self.setMinimumWidth(520)
        _bind_geometry(self, "rss_agg_dialog")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit((self.agg or {}).get("name", ""))
        self.in_name.setPlaceholderText("聚合名称（必填）")
        form.addRow("名称", self.in_name)

        self.combo_type = QtWidgets.QComboBox()
        self._type_keys = ["mixed", "keyword", "torrent"]
        for k in self._type_keys:
            self.combo_type.addItem(self.TYPE_LABELS[k], k)
        cur_type = (self.agg or {}).get("agg_type") or "mixed"
        if cur_type in self._type_keys:
            self.combo_type.setCurrentIndex(self._type_keys.index(cur_type))
        form.addRow("处理类型", self.combo_type)
        lay.addLayout(form)

        info = QtWidgets.QLabel(
            "混合：直接聚合成员条目；关键词：仅保留命中【必须】且【可选>1】且避开【禁止】的条目；"
            "磁链Hash：按 torrent_hash 折叠展示（保存时先快照）。")
        info.setWordWrap(True)
        info.setStyleSheet(f"QLabel {{ color:{_rss_colors()['text_secondary']}; font-size:12px; }}")
        lay.addWidget(info)

        # 处理类型说明随类型变化
        self.lb_hint = QtWidgets.QLabel("")
        self.lb_hint.setWordWrap(True)
        self.lb_hint.setStyleSheet(f"QLabel {{ color:{_rss_colors()['text_faint']}; font-size:12px; }}")
        lay.addWidget(self.lb_hint)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

        # 成员勾选
        members_group = QtWidgets.QGroupBox("成员")
        mg = QtWidgets.QVBoxLayout(members_group)
        self.member_list = QtWidgets.QListWidget()
        self.member_list.setMaximumHeight(160)
        self._load_members()
        mg.addWidget(self.member_list)
        lay.addWidget(members_group)

        # 关键词三桶
        kw_group = QtWidgets.QGroupBox("关键词三桶（仅关键词类型）")
        kg = QtWidgets.QVBoxLayout(kw_group)
        formk = QtWidgets.QFormLayout()
        self.in_required = QtWidgets.QLineEdit()
        self.in_required.setPlaceholderText("必须命中（每词都需命中，逗号/空格分隔）")
        self.in_optional = QtWidgets.QLineEdit()
        self.in_optional.setPlaceholderText("可选命中（至少一词，空=不限）")
        self.in_forbidden = QtWidgets.QLineEdit()
        self.in_forbidden.setPlaceholderText("禁止命中（每词都不得命中）")
        formk.addRow("必须", self.in_required)
        formk.addRow("可选", self.in_optional)
        formk.addRow("禁止", self.in_forbidden)
        kg.addLayout(formk)
        lay.addWidget(kw_group)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QtWidgets.QPushButton("保存")
        self.btn_ok.setStyleSheet(_btn_primary_style())
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        lay.addLayout(btn_row)

        self._fill_existing()

    def _load_members(self):
        self.member_items = []
        self.member_list.clear()
        if self.agg:
            prev_feed_ids = set(json.loads(self.agg.get("feed_ids") or "[]"))
            prev_tags = set(json.loads(self.agg.get("tags") or "[]"))
        else:
            prev_feed_ids = set()
            prev_tags = set()

        def feed_icon(feed):
            return _decode_feed_icon(feed.get("icon") or "")

        for f in self.store.list_feeds():
            icon = feed_icon(f)
            item = QtWidgets.QListWidgetItem(f"订阅源: {f['name']}")
            if icon:
                item.setIcon(icon)
            item.setData(QtCore.Qt.UserRole, ("feed", f["id"]))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if f["id"] in prev_feed_ids else QtCore.Qt.Unchecked)
            self.member_list.addItem(item)
            self.member_items.append(("feed", f["id"]))

        for tag in self.store.list_tags():
            item = QtWidgets.QListWidgetItem(f"标签: {tag}")
            item.setData(QtCore.Qt.UserRole, ("tag", tag))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if tag in prev_tags else QtCore.Qt.Unchecked)
            self.member_list.addItem(item)
            self.member_items.append(("tag", tag))

    def _fill_existing(self):
        if not self.agg:
            return
        self.in_required.setText(" ".join(json.loads(self.agg.get("kw_required") or "[]")))
        self.in_optional.setText(" ".join(json.loads(self.agg.get("kw_optional") or "[]")))
        self.in_forbidden.setText(" ".join(json.loads(self.agg.get("kw_forbidden") or "[]")))

    def _on_type_changed(self):
        k = self.combo_type.currentData()
        hint = {
            "mixed": "保留成员内全部已入库条目（可用过滤进一步筛选）。",
            "keyword": "必须∩可选∖禁止：每词命中标题或描述。",
            "torrent": "按 torrent_hash 分组折叠，点开查看成员条目。",
        }.get(k, "")
        self.lb_hint.setText(hint)

    def _on_ok(self):
        name = self.in_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "提示", "请填写聚合名称")
            return
        agg_type = self.combo_type.currentData()
        feed_ids = []
        tags = []
        for i in range(self.member_list.count()):
            it = self.member_list.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                kind, val = it.data(QtCore.Qt.UserRole)
                if kind == "feed":
                    feed_ids.append(val)
                else:
                    tags.append(val)
        if not feed_ids and not tags:
            QtWidgets.QMessageBox.warning(self, "提示", "请至少勾选一个成员（订阅源或标签）")
            return
        kw_required = _parse_keywords(self.in_required.text())
        kw_optional = _parse_keywords(self.in_optional.text())
        kw_forbidden = _parse_keywords(self.in_forbidden.text())
        if agg_type == "keyword" and not kw_required and not kw_optional:
            QtWidgets.QMessageBox.warning(self, "提示", "关键词类型至少需要【必须】或【可选】其一")
            return
        if self.agg_id:
            self.store.update_aggregation(
                self.agg_id, name=name, agg_type=agg_type, feed_ids=feed_ids, tags=tags,
                kw_required=kw_required, kw_optional=kw_optional, kw_forbidden=kw_forbidden)
            self.store.refresh_aggregation(self.agg_id)
        else:
            new_id = self.store.add_aggregation(
                name, agg_type=agg_type, feed_ids=feed_ids, tags=tags,
                kw_required=kw_required, kw_optional=kw_optional, kw_forbidden=kw_forbidden)
            self.store.refresh_aggregation(new_id)
        self.accept()


class _RssSidebar(QtWidgets.QWidget):
    """RSS 侧边栏（平铺）：全部条目 / 手动聚合 / 订阅源，支持排序与增删管理。

    节点选择后通过 page.on_sidebar_selection_changed() 驱动列表刷新。
    """

    SORT_OPTIONS = [
        ("更新时间↓", "updated", True),
        ("更新时间↑", "updated", False),
        ("名称↑", "name", False),
        ("名称↓", "name", True),
        ("添加时间↓", "added", True),
        ("添加时间↑", "added", False),
    ]

    def __init__(self, owner, page, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.page = page
        self._nodes = []
        self._sort_field = "name"
        self._sort_desc = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # 顶部：添加与管理按钮（图标化）
        qf = _qf()
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(4)
        self.btn_add_feed = qf["ToolButton"](qf["FluentIcon"].ADD)
        self.btn_add_feed.setToolTip("添加订阅源")
        self.btn_add_feed.setFixedSize(30, 28)
        self.btn_add_feed.clicked.connect(self._add_feed)
        top_row.addWidget(self.btn_add_feed)
        self.btn_add_agg = qf["PrimaryToolButton"](qf["FluentIcon"].FOLDER_ADD)
        self.btn_add_agg.setToolTip("添加聚合")
        self.btn_add_agg.setFixedSize(30, 28)
        self.btn_add_agg.clicked.connect(self._add_aggregation)
        top_row.addWidget(self.btn_add_agg)
        self.btn_manage_feed = qf["ToolButton"](qf["FluentIcon"].EDIT)
        self.btn_manage_feed.setToolTip("管理订阅源（添加 / 编辑 / 删除 / 启用停用）")
        self.btn_manage_feed.setFixedSize(30, 28)
        self.btn_manage_feed.clicked.connect(self.page._toggle_feed_section)
        top_row.addWidget(self.btn_manage_feed)
        lay.addLayout(top_row)

        # 排序行
        sort_row = QtWidgets.QHBoxLayout()
        sort_lb = qf["CaptionLabel"]("排序")
        sort_lb.setStyleSheet(f"color: {_rss_colors()['text_secondary']};")
        sort_row.addWidget(sort_lb)
        self.combo_sort = qf["ComboBox"]()
        for label, _f, _d in self.SORT_OPTIONS:
            self.combo_sort.addItem(label)
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.combo_sort, 1)
        lay.addLayout(sort_row)

        # 平铺节点列表
        self.list = QtWidgets.QListWidget()
        self.list.setSpacing(1)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        lay.addWidget(self.list, 1)

        # 概览与状态（刷新/全部刷新上方）
        sidebar_c = _rss_colors()
        self.lb_summary = qf["CaptionLabel"]("")
        self.lb_summary.setWordWrap(True)
        self.lb_summary.setStyleSheet(f"color: {sidebar_c['text_secondary']}; padding: 0 2px;")
        lay.addWidget(self.lb_summary)
        self.lb_status = QtWidgets.QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setStyleSheet(f"color: {sidebar_c['text_faint']}; padding: 0 2px;")
        lay.addWidget(self.lb_status)

        # 底部工具：统一刷新（下拉多选 + 一键全部刷新）
        bottom_row = QtWidgets.QHBoxLayout()

        self._refresh_ops = {
            "feeds": False,
            "scan": False,
            "icons": False,
            "aggs": False,
        }
        self.btn_refresh = QtWidgets.QToolButton()
        self.btn_refresh.setText("刷新 ▾")
        self.btn_refresh.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_refresh.setToolTip("选择本次刷新要执行的操作（可多选，执行所选后自动清除）")
        self.refresh_menu = QtWidgets.QMenu(self)
        self._refresh_actions = {}
        self._refresh_actions["feeds"] = self.refresh_menu.addAction("刷新订阅")
        self._refresh_actions["scan"] = self.refresh_menu.addAction("扫描磁力")
        self._refresh_actions["icons"] = self.refresh_menu.addAction("刷新图标")
        self._refresh_actions["aggs"] = self.refresh_menu.addAction("刷新聚合")
        for key, act in self._refresh_actions.items():
            act.setCheckable(True)
            act.toggled.connect(lambda checked, k=key: self._on_refresh_toggle(k, checked))
        self.refresh_menu.addSeparator()
        act_run = self.refresh_menu.addAction("执行所选")
        act_run.triggered.connect(self._run_selected_refresh)
        self.btn_refresh.setMenu(self.refresh_menu)

        self.btn_refresh_all = QtWidgets.QPushButton("全部刷新")
        self.btn_refresh_all.setToolTip("一键刷新：订阅 + 扫描磁力 + 图标 + 聚合")
        self.btn_refresh_all.setStyleSheet(_btn_primary_style())
        self.btn_refresh_all.clicked.connect(self._refresh_all_now)

        bottom_row.addWidget(self.btn_refresh)
        bottom_row.addWidget(self.btn_refresh_all)
        lay.addLayout(bottom_row)

        self.setStyleSheet(_sidebar_qss())

    # ── 数据加载与排序 ─────────────────────────────────────
    def _sort_nodes(self, nodes):
        field = self._sort_field
        desc = self._sort_desc

        def key(n):
            if field == "name":
                v = (n.get("name") or "").lower()
            elif field == "added":
                v = n.get("created_at") or ""
            else:  # updated（feeds.last_refresh / aggregations.last_refreshed）
                v = n.get("last_refresh") or n.get("last_refreshed") or ""
                return (v == "", v)
            return v

        return sorted(nodes, key=key, reverse=desc)

    def _apply_sort(self, index):
        cfg = self.owner.context.config
        if 0 <= index < len(self.SORT_OPTIONS):
            label, field, desc = self.SORT_OPTIONS[index]
            self._sort_field, self._sort_desc = field, desc
            cfg.set("rss.sidebar.sort", index)

    def reload(self, reselect=False):
        prev = self.current_data()
        self._apply_sort(self.combo_sort.currentIndex())
        self.list.blockSignals(True)
        self.list.clear()
        self._nodes = []
        data = self.owner.store.list_sidebar()
        cfg = self.owner.context.config

        def feed_icon(feed):
            icon = _decode_feed_icon(feed.get("icon") or "")
            if not icon or icon.isNull():
                return _qf()["FluentIcon"].GLOBE.icon()
            return icon

        rows = []  # (label, data, icon)

        _fic = _qf()["FluentIcon"]
        node_all = {"kind": "all", "name": "全部条目", "created_at": "", "last_refresh": ""}
        rows.append(("全部条目", node_all, _fic.HOME.icon()))

        for a in self._sort_nodes(data["aggregations"]):
            label = a["name"]
            info = "{}条".format(a.get("count") or 0)
            if a.get("unread"):
                info += "·未读{}".format(a["unread"])
            if a.get("agg_type") == "torrent":
                info += "·磁链"
            rows.append(("{} [{}]".format(label, info), {"kind": "agg", "agg_id": a["id"],
                          "agg_type": a.get("agg_type"), "name": label,
                          "created_at": a.get("created_at") or "", "last_refreshed": a.get("last_refreshed") or ""},
                         _fic.FOLDER.icon()))

        for f in self._sort_nodes([x for x in data["feeds"] if x.get("enabled")]):
            label = f["name"]
            if f.get("unread"):
                label += " ({})".format(f["unread"])
            rows.append((label, {"kind": "feed", "feed_id": f["id"], "name": f["name"],
                        "created_at": f.get("created_at") or "", "last_refresh": f.get("last_refresh") or ""},
                         feed_icon(f)))

        for label, d, icon in rows:
            item = QtWidgets.QListWidgetItem(label)
            if icon:
                item.setIcon(icon)
            item.setData(QtCore.Qt.UserRole, d)
            self.list.addItem(item)
            self._nodes.append(item)

        # 恢复选中
        def _match(item):
            d = item.data(QtCore.Qt.UserRole)
            if prev and d.get("kind") == prev.get("kind"):
                if d.get("kind") == "feed" and d.get("feed_id") == prev.get("feed_id"):
                    return True
                if d.get("kind") == "agg" and d.get("agg_id") == prev.get("agg_id"):
                    return True
                if d.get("kind") == "all":
                    return True
            return False

        restored = False
        if prev:
            for i in range(self.list.count()):
                if _match(self.list.item(i)):
                    self.list.setCurrentRow(i)
                    restored = True
                    break
        if restored:
            self.list.blockSignals(False)
            self.page.on_sidebar_selection_changed()
            return
        if not restored and reselect:
            snap = cfg.get("rss.sidebar.kind")
            if snap == "agg":
                aid = cfg.get("rss.sidebar.agg_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d.get("kind") == "agg" and d.get("agg_id") == aid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
            elif snap == "feed":
                fid = cfg.get("rss.sidebar.feed_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d.get("kind") == "feed" and d.get("feed_id") == fid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.page.on_sidebar_selection_changed()

    def current_data(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def current_filter(self):
        d = self.current_data()
        if not d:
            return {}
        kind = d.get("kind")
        if kind == "feed":
            return {"feed_ids": [d.get("feed_id")]}
        if kind == "agg":
            return {"agg_id": d.get("agg_id"), "agg_type": d.get("agg_type")}
        return {}

    # ── 事件 ──────────────────────────────────────────────
    def _on_sort_changed(self, index):
        self._apply_sort(index)
        self.reload()

    def _on_selection_changed(self):
        self.page.on_sidebar_selection_changed()

    def _on_double_clicked(self, item):
        d = item.data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg":
            self.page._open_aggregation(d.get("agg_id"))

    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        d = item.data(QtCore.Qt.UserRole)
        if not d:
            return
        menu = QtWidgets.QMenu(self)
        kind = d.get("kind")
        if kind == "agg":
            act_refresh = menu.addAction("刷新聚合")
            act_refresh.triggered.connect(lambda: self.owner.refresh_aggregation(d["agg_id"]))
            act_edit = menu.addAction("编辑聚合")
            act_edit.triggered.connect(lambda: self._edit_aggregation(d["agg_id"]))
            act_del = menu.addAction("删除聚合")
            act_del.triggered.connect(lambda: self._remove_aggregation(d["agg_id"]))
        elif kind == "feed":
            act_edit = menu.addAction("编辑订阅")
            act_edit.triggered.connect(lambda: self._edit_feed(d["feed_id"]))
            act_toggle = menu.addAction("启用/停用")
            act_toggle.triggered.connect(lambda: self._toggle_feed(d["feed_id"]))
            act_del = menu.addAction("删除订阅")
            act_del.triggered.connect(lambda: self._remove_feed(d["feed_id"]))
        else:
            act = menu.addAction("刷新")
            act.triggered.connect(self.page._refresh)
        menu.exec(self.mapToGlobal(pos))

    # ── 操作 ──────────────────────────────────────────────
    def _add_feed(self):
        self.page._show_add_feed()

    def _add_aggregation(self):
        self.page._show_add_aggregation()

    def _edit_aggregation(self, agg_id):
        self.page._show_edit_aggregation(agg_id)

    def _remove_aggregation(self, agg_id):
        if not QtWidgets.QMessageBox.question(self, "删除聚合", "确定删除该聚合？") == QtWidgets.QMessageBox.Yes:
            return
        self.owner.store.remove_aggregation(agg_id)
        self.page._reload_sidebar()
        self.page.on_sidebar_selection_changed()

    def _edit_feed(self, feed_id):
        feed = self.owner.store.get_feed_by_id(feed_id)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self.page)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.page._reload_sidebar()
            self.page._load_items(preserve_scroll=True)

    def _toggle_feed(self, feed_id):
        feed = self.owner.store.get_feed_by_id(feed_id)
        if feed:
            self.owner.store.set_feed_enabled(feed_id, not feed["enabled"])
            self.page._reload_sidebar()

    def _remove_feed(self, feed_id):
        if not QtWidgets.QMessageBox.question(self, "删除订阅", "确定删除该订阅源？") == QtWidgets.QMessageBox.Yes:
            return
        self.owner.store.remove_feed(feed_id)
        self.page._reload_sidebar()
        self.page.on_sidebar_selection_changed()

    def _scan_magnet(self):
        self.owner.scan_hashes(limit=self.owner.context.config.get("rss.scan_limit", 200))

    def _refresh_icons(self):
        self.owner.refresh_favicons()

    def _refresh_all_aggs(self):
        self.owner.refresh_all_aggregations()

    def _on_refresh_toggle(self, key, checked):
        self._refresh_ops[key] = checked

    def _run_selected_refresh(self):
        selected = [k for k, v in self._refresh_ops.items() if v]
        if not selected:
            return
        # 先清除勾选（toggled(False) 会同步 _refresh_ops），再执行
        for act in self._refresh_actions.values():
            if act.isChecked():
                act.setChecked(False)
        self._run_refresh_ops(selected)

    def _refresh_all_now(self):
        self._run_refresh_ops(["feeds", "scan", "icons", "aggs"])

    def _run_refresh_ops(self, ops):
        for op in ops:
            try:
                if op == "feeds":
                    self.owner.refresh_now()
                elif op == "scan":
                    self.owner.scan_hashes(limit=self.owner.context.config.get("rss.scan_limit", 200))
                elif op == "icons":
                    self.owner.refresh_favicons()
                elif op == "aggs":
                    self.owner.refresh_all_aggregations()
            except Exception as ex:
                logger.warning("刷新操作 %s 失败: %s", op, ex)



class _RssPageWidget(QtWidgets.QWidget):
    frameless = True  # 打开时使用无边框自定义标题栏窗口

    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self._current_page = 0
        self._all_items = []
        self._last_clicked_row = -1
        self._selected_hashes = set()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        self._node_item_by_head = {}
        self._group_children = {}
        self._head_buttons = {}
        self._head_by_member = {}

        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)

        rss_c = _rss_colors()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = _RssSidebar(owner, self)
        self._sidebar.setStyleSheet(_sidebar_qss())
        # 概览与状态 Label 位于侧边栏刷新/全部刷新上方，此处仅建立别名
        self.lb_status = self._sidebar.lb_status
        self.lb_summary = self._sidebar.lb_summary

        section_items = QtWidgets.QVBoxLayout()
        section_items.setContentsMargins(0, 0, 0, 0)
        section_items.setSpacing(8)

        qf = _qf()

        # ── 单行工具条：筛选 / 搜索 / 视图开关 / 批量 ─────────
        tool_row = QtWidgets.QHBoxLayout()
        tool_row.setSpacing(6)

        self._date_preset_labels = {"today": "今天", "week": "本周", "month": "本月"}
        self.btn_date_filter = qf["DropDownPushButton"]("时间筛选")
        self.btn_date_filter.setToolTip("按发布时间筛选（快捷区间或自定义日期范围）")
        self._date_menu = qf["RoundMenu"](parent=self)
        self._date_quick_actions = {}
        _date_group = QtGui.QActionGroup(self._date_menu)
        for _key, _label in self._date_preset_labels.items():
            act = QtGui.QAction(_label, self._date_menu)
            self._date_menu.addAction(act)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked, k=_key: self._set_date_preset(k))
            _date_group.addAction(act)
            self._date_quick_actions[_key] = act
        act_clear_date = QtGui.QAction("清除时间筛选", self._date_menu)
        self._date_menu.addAction(act_clear_date)
        act_clear_date.triggered.connect(lambda: self._set_date_preset(None))
        self._date_menu.addSeparator()
        _date_wg = QtWidgets.QWidget()
        _date_row = QtWidgets.QHBoxLayout(_date_wg)
        _date_row.setContentsMargins(14, 6, 14, 8)
        _date_row.setSpacing(6)
        _date_row.addWidget(QtWidgets.QLabel("从"))
        self.date_from = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("yyyy-MM-dd")
        _date_row.addWidget(self.date_from)
        _date_row.addWidget(QtWidgets.QLabel("到"))
        self.date_to = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("yyyy-MM-dd")
        _date_row.addWidget(self.date_to)
        _btn_range_apply = QtWidgets.QPushButton("应用")
        _btn_range_apply.clicked.connect(self._apply_date_range)
        _date_row.addWidget(_btn_range_apply)
        _btn_range_clear = QtWidgets.QPushButton("清除")
        _btn_range_clear.clicked.connect(lambda: self._set_date_preset(None))
        _date_row.addWidget(_btn_range_clear)
        _act_range = QtWidgets.QWidgetAction(self._date_menu)
        _act_range.setDefaultWidget(_date_wg)
        self._date_menu.addAction(_act_range)
        self.btn_date_filter.setMenu(self._date_menu)
        tool_row.addWidget(self.btn_date_filter)

        self.combo_tag = qf["ComboBox"]()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        self.combo_tag.setMinimumWidth(120)
        self.combo_tag.currentIndexChanged.connect(self._load_items)
        tool_row.addWidget(self.combo_tag)

        self.combo_search_field = qf["ComboBox"]()
        self.combo_search_field.addItems(["全部", "标题", "描述", "链接"])
        self.combo_search_field.setFixedWidth(86)
        self.combo_search_field.currentIndexChanged.connect(self._load_items)
        tool_row.addWidget(self.combo_search_field)

        self.search_input = qf["SearchLineEdit"]()
        self.search_input.setPlaceholderText("搜索标题 / 描述 / 链接…")
        self.search_input.setMinimumWidth(120)
        self.search_input.returnPressed.connect(self._load_items)
        self.search_input.searchSignal.connect(self._load_items)
        self.search_input.clearSignal.connect(self._load_items)
        tool_row.addWidget(self.search_input, 1)

        self._current_date_range = None

        self.btn_favorites = qf["ToggleButton"]("仅收藏")
        self.btn_favorites.setCheckable(True)
        self.btn_favorites.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_favorites)

        self.btn_unread = qf["ToggleButton"]("仅未读")
        self.btn_unread.setCheckable(True)
        self.btn_unread.toggled.connect(self._load_items)
        tool_row.addWidget(self.btn_unread)

        self.chk_select_all = qf["CheckBox"]("全选")
        self.chk_select_all.stateChanged.connect(self._select_all)
        tool_row.addWidget(self.chk_select_all)

        self.btn_batch_ops = qf["PrimaryDropDownPushButton"]("批量操作")
        self.btn_batch_ops.setToolTip("对选中条目执行批量操作")
        self._batch_menu = qf["RoundMenu"](parent=self)
        self._batch_actions = {}
        _act_read = QtGui.QAction("标记已读", self._batch_menu)
        self._batch_menu.addAction(_act_read)
        _act_read.triggered.connect(self._batch_mark_read)
        self._batch_actions["read"] = _act_read
        _act_unread = QtGui.QAction("标记未读", self._batch_menu)
        self._batch_menu.addAction(_act_unread)
        _act_unread.triggered.connect(self._batch_mark_unread)
        self._batch_actions["unread"] = _act_unread
        _act_delete = QtGui.QAction("删除选中", self._batch_menu)
        self._batch_menu.addAction(_act_delete)
        _act_delete.triggered.connect(self._batch_delete)
        self._batch_actions["delete"] = _act_delete
        self._batch_menu.addSeparator()
        _act_all_read = QtGui.QAction("全部已读", self._batch_menu)
        self._batch_menu.addAction(_act_all_read)
        _act_all_read.triggered.connect(self._mark_all_read)
        self.btn_batch_ops.setMenu(self._batch_menu)
        tool_row.addWidget(self.btn_batch_ops)

        self._update_batch_buttons()
        section_items.addLayout(tool_row)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(3)

        self.item_list = QtWidgets.QListWidget()
        self.item_list.setObjectName("rssItemList")
        self.item_list.setAlternatingRowColors(False)
        self.item_list.viewport().setAutoFillBackground(False)
        self.item_list.setStyleSheet(
            ("QListWidget {{ background: {panel}; border: none; border-radius: 8px; }}"
             "QListWidget::item {{ padding: 2px 4px; border-radius: 6px; }}"
             "QListWidget::item:selected {{ background: {row_selected}; }}"
             "QListWidget::item:hover {{ background: {row_hover}; }}").format(**rss_c)
        )
        self.item_list.itemDoubleClicked.connect(self._open_item)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.itemChanged.connect(self._on_item_changed)
        self.item_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.item_list.customContextMenuRequested.connect(self._show_context_menu)
        splitter.addWidget(self.item_list)

        self._summary_title = QtWidgets.QLabel("点击左侧条目查看摘要…")
        self._summary_title.setWordWrap(True)
        self._summary_title.setStyleSheet(
            "QLabel { font-size: 15px; font-weight: bold; background: transparent; }"
        )
        self._summary_meta = QtWidgets.QLabel("")
        self._summary_meta.setWordWrap(True)
        self._summary_meta.setStyleSheet(
            f"QLabel {{ color: {rss_c['text_secondary']}; font-size: 12px; background: transparent; }}"
        )
        self._summary_desc = QtWidgets.QLabel("")
        self._summary_desc.setWordWrap(True)
        self._summary_desc.setMaximumHeight(120)
        self._summary_desc.setStyleSheet(
            "QLabel { font-size: 12px; background: transparent; }"
        )
        self._summary_desc.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        self._preview_container = QtWidgets.QWidget()
        preview_panel = QtWidgets.QVBoxLayout(self._preview_container)
        preview_panel.setContentsMargins(0, 0, 0, 0)
        preview_panel.setSpacing(4)
        preview_panel.addWidget(self._summary_title)
        preview_panel.addWidget(self._summary_meta)
        preview_panel.addWidget(self._summary_desc)

        # WebEngine 初始化为惰性创建：首次展示预览时才构造，避免拖慢 RSS 页打开。
        self._preview_web_ok = False
        self._preview_text_view = None
        self._preview_browser_view = None
        self.preview_browser = None
        self._preview_placeholder = QtWidgets.QLabel(
            "点击左侧条目，即可在下方预览文章正文…\n（原文链接用系统浏览器打开）")
        self._preview_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._preview_placeholder.setWordWrap(True)
        self._preview_placeholder.setStyleSheet(
            f"color: {rss_c['text_faint']}; font-size: 13px; padding: 20px;")
        self._preview_stack = QtWidgets.QStackedWidget()
        self._preview_stack.setStyleSheet(
            ("QStackedWidget {{ background: {panel}; border-radius: 8px; }}").format(**rss_c)
        )
        self._summary_panel = QtWidgets.QWidget()
        self._summary_panel.setAutoFillBackground(False)
        _sum_lay = QtWidgets.QVBoxLayout(self._summary_panel)
        _sum_lay.setContentsMargins(0, 0, 0, 0)
        _sum_lay.addWidget(self._preview_placeholder)
        self._preview_stack.addWidget(self._summary_panel)
        self._preview_stack.setCurrentWidget(self._summary_panel)
        # 预览加载去抖：条目点击/标题按钮/聚合头等多个入口常在同帧触发 3 次
        # 加载。若对同一 WebEngine 视图并发 load()，会把主线程卡死在合成器
        # 里（复现为 GUI 冻结），因此窗口期内只保留最后一次加载请求。
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self._preview_do_load)
        self._preview_pending = None
        self._preview_fallback = None
        preview_panel.addWidget(self._preview_stack, 1)

        splitter.addWidget(self._preview_container)

        splitter.setSizes([500, 300])
        self._preview_splitter = splitter
        section_items.addWidget(splitter, 1)

        page_row = QtWidgets.QHBoxLayout()
        page_row.setSpacing(6)
        page_row.addStretch(1)
        _pg_c = _rss_colors()
        self.btn_prev = QtWidgets.QPushButton("上一页")
        self.btn_prev.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        self.btn_prev.clicked.connect(self._prev_page)
        page_row.addWidget(self.btn_prev)

        self.lb_page = QtWidgets.QLabel("第 1 页")
        self.lb_page.setAlignment(QtCore.Qt.AlignCenter)
        self.lb_page.setStyleSheet(f"color: {_pg_c['text_secondary']}; padding: 0 4px;")
        page_row.addWidget(self.lb_page)

        self.btn_next = QtWidgets.QPushButton("下一页")
        self.btn_next.setStyleSheet(_btn_style(min_width=0, padding="3px 14px", radius=6))
        self.btn_next.clicked.connect(self._next_page)
        page_row.addWidget(self.btn_next)

        page_row.addStretch(1)

        self.lb_total = QtWidgets.QLabel("")
        self.lb_total.setStyleSheet(f"color: {_pg_c['text_secondary']}; padding-right: 6px;")
        page_row.addWidget(self.lb_total)

        section_items.addLayout(page_row)

        outer = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer.setHandleWidth(3)
        outer.addWidget(self._sidebar)

        content_wrap = QtWidgets.QWidget()
        content_wrap.setObjectName("rssContentWrap")
        content_wrap.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        content_wrap.setStyleSheet(
            ("QWidget#rssContentWrap {{ background: {panel_soft}; border-radius: 10px; }}").format(**rss_c)
        )
        wrap = QtWidgets.QVBoxLayout(content_wrap)
        wrap.setContentsMargins(12, 12, 12, 12)
        wrap.setSpacing(8)
        wrap.addLayout(section_items)
        outer.addWidget(content_wrap)
        outer.setSizes([240, 900])
        root.addWidget(outer)

        with timed("rss.open.sidebar_reload"):
            self._sidebar.reload(reselect=True)
        with timed("rss.open.favicon_check"):
            if self.owner.store.feeds_needing_favicon():
                self.owner.refresh_favicons()
        self.setTabOrder(self.search_input, self.item_list)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        with timed("rss.open.load_items"):
            self._load_items()

        self.destroyed.connect(self._cleanup_preview)

    def _cleanup_preview(self):
        """页面销毁时清理本地引用，但保留全局 WebEngine 单例。

        旧代码在 destroyed 时清除 _PREVIEW_KEEP["view"]，导致下次打开模块
        重新创建 QWebEngineProfile → 新 Chromium 子进程 → 线程无限增长。
        新逻辑：先把视图从 QStackedWidget 中摘除（避免 Qt 父子析构链销毁
        C++ 对象），再清空本地引用，但保留 _PREVIEW_KEEP 让下次打开可复用。"""
        global _PREVIEW_KEEP
        try:
            self._preview_timer.stop()
        except Exception:
            pass
        # 从 stack 中摘除视图，防止 Qt 销毁子控件时连带销毁 C++ 视图
        if self._preview_browser_view is not None:
            try:
                self._preview_stack.removeWidget(self._preview_browser_view)
                self._preview_browser_view.setParent(None)
            except Exception:
                pass
        self._preview_browser_view = None
        self._preview_text_view = None
        self.preview_browser = None

    def paintEvent(self, event):
        # 独立页窗口：与主窗口一致的壁纸+毛玻璃背景（无壁纸时回退默认渲染）
        try:
            from core.theme import paint_wallpaper_glass
            cfg = self.owner.context.config
            painter = QtGui.QPainter(self)
            painted = paint_wallpaper_glass(self, painter, cfg)
            painter.end()
            if not painted:
                super().paintEvent(event)
        except Exception:
            super().paintEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_J:
            row = self.item_list.currentRow()
            if row < self.item_list.count() - 1:
                self.item_list.setCurrentRow(row + 1)
        elif event.key() == QtCore.Qt.Key_K:
            row = self.item_list.currentRow()
            if row > 0:
                self.item_list.setCurrentRow(row - 1)
        elif event.key() == QtCore.Qt.Key_Return or event.key() == QtCore.Qt.Key_Enter:
            item = self.item_list.currentItem()
            if item:
                self._open_item(item)
        elif event.key() == QtCore.Qt.Key_S:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                self.owner.store.toggle_favorite(h)
                self._load_items()
        elif event.key() == QtCore.Qt.Key_R:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                if self.owner.store.is_read(h):
                    self.owner.store.mark_unread(h)
                else:
                    self.owner.store.mark_read(h)
                self._load_items()
        elif event.key() == QtCore.Qt.Key_C:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                text = self.owner.store.share_item(h)
                if text:
                    QtWidgets.QApplication.clipboard().setText(text)
                    self.lb_status.setText("已复制到剪贴板")
        else:
            super().keyPressEvent(event)

    def _update_date_filter_ui(self):
        """同步时间筛选按钮文字与快捷项勾选状态。"""
        dr = self._current_date_range
        act_map = self._date_quick_actions
        for key, act in act_map.items():
            act.setChecked(dr == key)
        if not dr:
            self.btn_date_filter.setText("时间筛选")
        elif isinstance(dr, str):
            self.btn_date_filter.setText(f"时间：{self._date_preset_labels.get(dr, dr)}")
        else:
            date_from, date_to = dr[1], dr[2]
            label_from = date_from[5:] if len(date_from) == 10 else date_from
            label_to = date_to[5:] if len(date_to) == 10 else date_to
            self.btn_date_filter.setText(f"时间：{label_from}~{label_to}")

    def _set_date_preset(self, key):
        """设置快捷时间区间（today/week/month），key=None 表示清除。"""
        if key in self._date_preset_labels:
            self._current_date_range = key
        else:
            self._current_date_range = None
        self._update_date_filter_ui()
        self._load_items()

    def _apply_date_range(self):
        """应用自定义起止日期范围。"""
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        if date_from > self.date_to.date().toString("yyyy-MM-dd"):
            QtWidgets.QMessageBox.information(self, "日期范围", "开始日期不应晚于结束日期。")
            return
        self._current_date_range = ("range", date_from, date_to)
        self._update_date_filter_ui()
        self._date_menu.close()
        self._load_items()

    def _build_feed_section(self):
        self.feed_section = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.feed_section)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.feed_list = QtWidgets.QListWidget()
        self.feed_list.setMinimumHeight(80)
        self.feed_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.feed_list.model().rowsMoved.connect(self._on_feed_order_changed)
        lay.addWidget(self.feed_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("添加订阅")
        btn_add.clicked.connect(self._show_add_dialog)
        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.clicked.connect(self._edit_feed)
        btn_del = QtWidgets.QPushButton("删除选中")
        btn_del.clicked.connect(self._remove_feed)
        btn_toggle = QtWidgets.QPushButton("启用/停用")
        btn_toggle.clicked.connect(self._toggle_feed)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_toggle)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.feed_section.setVisible(False)

        root = self.layout()
        root.insertWidget(0, self.feed_section)
        self._load_feeds()

    def _build_settings_section(self):
        self.settings_section = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.settings_section)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        settings_group = QtWidgets.QGroupBox("代理设置")
        settings_lay = QtWidgets.QFormLayout(settings_group)
        self.in_proxy = QtWidgets.QLineEdit()
        self.in_proxy.setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self.in_proxy.setText(self.owner.context.config.get("rss.proxy", ""))
        self.in_proxy.returnPressed.connect(self._save_proxy)
        settings_lay.addRow("代理地址", self.in_proxy)
        lay.addWidget(settings_group)

        cleanup_group = QtWidgets.QGroupBox("数据清理")
        cleanup_lay = QtWidgets.QHBoxLayout(cleanup_group)
        cleanup_lay.addWidget(QtWidgets.QLabel("清理"))
        self.spin_cleanup_days = QtWidgets.QSpinBox()
        self.spin_cleanup_days.setRange(7, 365)
        self.spin_cleanup_days.setValue(self.owner.context.config.get("rss.cleanup_days", 30))
        self.spin_cleanup_days.setSuffix(" 天前的数据")
        cleanup_lay.addWidget(self.spin_cleanup_days)
        btn_cleanup = QtWidgets.QPushButton("清理")
        btn_cleanup.setStyleSheet(_btn_primary_style())
        btn_cleanup.clicked.connect(self._cleanup_old)
        cleanup_lay.addWidget(btn_cleanup)
        lay.addWidget(cleanup_group)

        notify_group = QtWidgets.QGroupBox("通知设置")
        notify_lay = QtWidgets.QFormLayout(notify_group)
        self.chk_notify = QtWidgets.QCheckBox("启用桌面通知")
        self.chk_notify.setChecked(self.owner.context.config.get("rss.notification_enabled", True))
        self.chk_notify.stateChanged.connect(lambda s: self.owner.context.config.set("rss.notification_enabled", s == QtCore.Qt.CheckState.Checked.value))
        notify_lay.addRow(self.chk_notify)
        lay.addWidget(notify_group)

        categories_group = QtWidgets.QGroupBox("分类管理")
        categories_lay = QtWidgets.QVBoxLayout(categories_group)
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setMaximumHeight(80)
        categories_lay.addWidget(self.category_list)
        cat_btn_row = QtWidgets.QHBoxLayout()
        btn_add_cat = QtWidgets.QPushButton("添加分类")
        btn_add_cat.setStyleSheet(_btn_style())
        btn_add_cat.clicked.connect(self._show_category_dialog)
        btn_edit_cat = QtWidgets.QPushButton("编辑")
        btn_edit_cat.setStyleSheet(_btn_style())
        btn_edit_cat.clicked.connect(self._edit_category)
        btn_del_cat = QtWidgets.QPushButton("删除")
        btn_del_cat.setStyleSheet(_btn_style())
        btn_del_cat.clicked.connect(self._remove_category)
        cat_btn_row.addWidget(btn_add_cat)
        cat_btn_row.addWidget(btn_edit_cat)
        cat_btn_row.addWidget(btn_del_cat)
        cat_btn_row.addStretch(1)
        categories_lay.addLayout(cat_btn_row)
        lay.addWidget(categories_group)

        keywords_group = QtWidgets.QGroupBox("关键词提醒")
        keywords_lay = QtWidgets.QVBoxLayout(keywords_group)
        self.keyword_list = QtWidgets.QListWidget()
        self.keyword_list.setMaximumHeight(80)
        keywords_lay.addWidget(self.keyword_list)
        kw_btn_row = QtWidgets.QHBoxLayout()
        btn_add_kw = QtWidgets.QPushButton("添加关键词")
        btn_add_kw.setStyleSheet(_btn_style())
        btn_add_kw.clicked.connect(self._show_keyword_dialog)
        btn_del_kw = QtWidgets.QPushButton("删除选中")
        btn_del_kw.setStyleSheet(_btn_style())
        btn_del_kw.clicked.connect(self._remove_keyword)
        kw_btn_row.addWidget(btn_add_kw)
        kw_btn_row.addWidget(btn_del_kw)
        kw_btn_row.addStretch(1)
        keywords_lay.addLayout(kw_btn_row)
        lay.addWidget(keywords_group)

        rules_group = QtWidgets.QGroupBox("过滤规则")
        rules_lay = QtWidgets.QVBoxLayout(rules_group)
        self.rule_list = QtWidgets.QListWidget()
        self.rule_list.setMaximumHeight(80)
        rules_lay.addWidget(self.rule_list)
        rule_btn_row = QtWidgets.QHBoxLayout()
        btn_add_rule = QtWidgets.QPushButton("添加规则")
        btn_add_rule.setStyleSheet(_btn_style())
        btn_add_rule.clicked.connect(self._show_filter_dialog)
        btn_del_rule = QtWidgets.QPushButton("删除选中")
        btn_del_rule.setStyleSheet(_btn_style())
        btn_del_rule.clicked.connect(self._remove_rule)
        btn_toggle_rule = QtWidgets.QPushButton("启用/禁用")
        btn_toggle_rule.setStyleSheet(_btn_style())
        btn_toggle_rule.clicked.connect(self._toggle_rule)
        rule_btn_row.addWidget(btn_add_rule)
        rule_btn_row.addWidget(btn_del_rule)
        rule_btn_row.addWidget(btn_toggle_rule)
        rule_btn_row.addStretch(1)
        rules_lay.addLayout(rule_btn_row)
        lay.addWidget(rules_group)

        history_group = QtWidgets.QGroupBox("阅读历史")
        history_lay = QtWidgets.QVBoxLayout(history_group)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setMaximumHeight(100)
        history_lay.addWidget(self.history_list)
        btn_refresh_history = QtWidgets.QPushButton("刷新历史")
        btn_refresh_history.setStyleSheet(_btn_style())
        btn_refresh_history.clicked.connect(self._load_history)
        history_lay.addWidget(btn_refresh_history)
        lay.addWidget(history_group)

        stats_group = QtWidgets.QGroupBox("统计信息")
        stats_lay = QtWidgets.QVBoxLayout(stats_group)
        self.lb_stats = QtWidgets.QLabel("")
        stats_lay.addWidget(self.lb_stats)
        btn_refresh_stats = QtWidgets.QPushButton("刷新统计")
        btn_refresh_stats.setStyleSheet(_btn_style())
        btn_refresh_stats.clicked.connect(self._load_stats)
        stats_lay.addWidget(btn_refresh_stats)
        lay.addWidget(stats_group)

        lay.addStretch(1)

        self.settings_section.setVisible(False)
        root = self.layout()
        root.insertWidget(1, self.settings_section)
        self._load_keywords()
        self._load_rules()
        self._load_stats()
        self._load_categories()
        self._load_history()

    def _toggle_feed_section(self):
        dlg = _FeedManageDialog(self.owner, self)
        dlg.exec()
        self._load_tag_filter()
        self._load_items(preserve_scroll=True)

    def _toggle_settings_section(self):
        dlg = _SettingsDialog(self.owner, self)
        dlg.exec()
        self._load_items(preserve_scroll=True)

    def on_refreshed(self, counts):
        self._load_items(preserve_scroll=True)
        self._reload_sidebar()
        if counts:
            parts = ["{}: {}/{}".format(n, added, total) for n, tag, total, added in counts]
            self.lb_status.setText("刷新完成 — " + ", ".join(parts))
            self._notify("刷新完成", " · ".join(parts))
        else:
            self.lb_status.setText("刷新完成")
            self._notify("刷新完成", "没有新内容")
        self._refresh_header_summary()

    def on_feed_done(self, info):
        self._load_items(preserve_scroll=True)
        self._reload_sidebar()
        self._refresh_header_summary()

    def _refresh_header_summary(self):
        """刷新头部概览：订阅 / 聚合 / 未读 / 最近更新时间。"""
        if not hasattr(self, "lb_summary"):
            return
        try:
            data = self.owner.store.list_sidebar()
            feeds = len([f for f in data.get("feeds", []) if f.get("enabled")])
            aggs = len(data.get("aggregations", []))
            parts = [f"订阅 {feeds}", f"聚合 {aggs}"]
            unread = 0
            for f in data.get("feeds", []):
                unread += int(f.get("unread") or 0)
            if unread:
                parts.insert(1, f"未读 {unread}")
            last = (data.get("aggregations") or [{}])[0].get("last_refreshed") or ""
            if last:
                self.lb_summary.setText(" · ".join(parts + [f"更新 {str(last)[:16]}"]))
            else:
                self.lb_summary.setText(" · ".join(parts))
        except Exception:
            self.lb_summary.setText("")

    def _notify(self, title, content="", level="success"):
        """弹出轻量 InfoBar 提示；仅在页面可见时弹，失败静默。"""
        try:
            if not (self.isVisible() and self.window().isVisible()):
                return
            from qfluentwidgets import InfoBar, InfoBarPosition
            getattr(InfoBar, level)(title=title, content=content, parent=self.window(),
                                    position=InfoBarPosition.TOP_RIGHT, duration=3000)
        except Exception:
            pass

    def _reload_sidebar(self):
        if hasattr(self, "_sidebar"):
            self._sidebar.reload()

    def on_sidebar_selection_changed(self):
        cfg = self.owner.context.config
        sel = self._sidebar.current_filter()
        kind = None
        d = self._sidebar.current_data() or {}
        kind = (d or {}).get("kind")
        cfg.set("rss.sidebar.kind", kind)
        cfg.set("rss.sidebar.feed_id", (d or {}).get("feed_id") if kind == "feed" else None)
        cfg.set("rss.sidebar.agg_id", (d or {}).get("agg_id") if kind == "agg" else None)
        cfg.set("rss.sidebar.keyword", None)
        cfg.set("rss.sidebar.torrent_hash", None)
        self._current_page = 0
        self._load_items()

    def on_hash_scan_done(self, scanned):
        self._load_items(preserve_scroll=True)
        self._reload_sidebar()

    def on_favicons_loaded(self):
        self._reload_sidebar()

    def _load_feeds(self):
        self.feed_list.clear()
        for f in self.owner.store.list_feeds():
            status = "✓" if f["enabled"] else "✗"
            group = f" [{f['group_name']}]" if f.get("group_name") else ""
            error = f" ⚠{f['last_error'][:30]}" if f.get("last_error") else ""
            kind = " [监控]" if f.get("feed_type") == "scrape" else ""
            text = "{}{} {}{}{} — {}{}".format(status, kind, f["name"], group, "", f["url"], error)
            tags = f.get("tags") or ([f["tag"]] if f.get("tag") else [])
            tags = [t for t in tags if t and t != f["name"]]
            if tags:
                text += "  (标签: {})".format(", ".join(tags))
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, f["id"])
            item.setData(QtCore.Qt.UserRole + 1, f["enabled"])
            self.feed_list.addItem(item)

    def _on_feed_order_changed(self):
        feed_ids = []
        for i in range(self.feed_list.count()):
            item = self.feed_list.item(i)
            feed_ids.append(item.data(QtCore.Qt.UserRole))
        self.owner.store.update_feed_order(feed_ids)

    def _edit_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        feed = self.owner.store.get_feed_by_id(fid)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _load_tag_filter(self):
        current = self.combo_tag.currentData()
        self.combo_tag.blockSignals(True)
        self.combo_tag.clear()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        for tag in self.owner.store.list_tags():
            self.combo_tag.addItem(tag, tag)
        if current:
            idx = self.combo_tag.findData(current)
            if idx >= 0:
                self.combo_tag.setCurrentIndex(idx)
        self.combo_tag.blockSignals(False)

    def _show_add_dialog(self):
        dlg = _AddFeedDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()
            self._load_tag_filter()

    def _remove_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_feed(fid)
        self._load_feeds()
        self._load_tag_filter()

    def _toggle_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        enabled = item.data(QtCore.Qt.UserRole + 1)
        self.owner.store.set_feed_enabled(fid, not enabled)
        self._load_feeds()

    def _load_items(self, preserve_scroll=False):
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = None
        if preserve_scroll and scrollbar is not None:
            prev_value = scrollbar.value()

        query = self.search_input.text().strip()
        fav_only = self.btn_favorites.isChecked()
        unread_only = self.btn_unread.isChecked()

        field_map = {"全部": None, "标题": "title", "描述": "description", "链接": "link"}
        search_field = field_map.get(self.combo_search_field.currentText())

        if query:
            self._all_items = self.owner.store.search(query, 5000, field=search_field)
            torrent_filter = None
        else:
            tag_filter = self.combo_tag.currentData()
            sel = self._sidebar.current_filter() if hasattr(self, "_sidebar") else {}
            agg_type = sel.get("agg_type")
            if agg_type == "torrent":
                agg_id = sel.get("agg_id")
                self._load_torrent_aggregation(agg_id)
                return
            torrent_filter = None
            self._all_items = self.owner.store.recent(
                5000, tag_filter=tag_filter, favorites_only=fav_only, unread_only=unread_only,
                date_range=self._current_date_range,
                feed_ids=sel.get("feed_ids"),
                agg_id=sel.get("agg_id"),
                keyword=sel.get("keyword"),
                torrent_hash=torrent_filter,
            )

        self._load_tag_filter()
        total = len(self._all_items)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._current_page = min(self._current_page, total_pages - 1)
        start = self._current_page * PAGE_SIZE
        page_items = self._all_items[start : start + PAGE_SIZE]

        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        for it in page_items:
            is_checked = it["hash"] in self._selected_hashes
            row_widget, title_btn, chk = _make_item_row(self.item_list, it, None, checked=is_checked)
            title_btn.clicked.connect(lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
            chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))

            self._item_title_btns[it["hash"]] = title_btn
            self._item_checkboxes[it["hash"]] = chk

            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            item.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
            item.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
            self.item_list.addItem(item)
            self.item_list.setItemWidget(item, row_widget)

        self.lb_page.setText(f"第 {self._current_page + 1}/{total_pages} 页")
        if torrent_filter:
            srcs = set()
            for it in self._all_items:
                for t in (it.get("tags") or "").split("|"):
                    t = t.strip()
                    if t:
                        srcs.add(t)
            self.lb_total.setText(f"磁链聚合 ◈ {len(srcs)} 个来源 · 共 {total} 条")
        else:
            self.lb_total.setText(f"共 {total} 条")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < total_pages - 1)

        QtCore.QTimer.singleShot(0, self._sync_row_heights)

        if prev_value is not None:
            QtCore.QTimer.singleShot(
                0, lambda sb=scrollbar, v=prev_value, m=scrollbar.maximum(): sb.setValue(min(v, m))
            )

        self._refresh_header_summary()

    def _sync_row_heights(self):
        """按当前列表宽度重算各行高度，使可换行标题自适应行高，并计入样式内边距避免截断。"""
        list_w = self.item_list
        # 条目自身左右留白(item padding 4px*2 + 外边距余量)
        style_pad = 8
        vp_w = list_w.viewport().width() - 8 - style_pad
        if vp_w <= 0:
            vp_w = 400
        for row in range(list_w.count()):
            item = list_w.item(row)
            wid = list_w.itemWidget(item)
            if wid is None:
                continue
            h = None
            try:
                if wid.hasHeightForWidth():
                    h = wid.heightForWidth(vp_w)
            except Exception:
                h = None
            if not h or h <= 0:
                h = wid.sizeHint().height()
            # 保证标题至少完整显示一行，并留底部余量避免截断
            h = max(h, 40)
            item.setSizeHint(QtCore.QSize(vp_w + 8 + style_pad, int(h)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_items()

    def _next_page(self):
        total_pages = max(1, (len(self._all_items) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._load_items()

    def _load_torrent_aggregation(self, agg_id):
        """磁链hash类型聚合：方案B —— 每个 torrent_hash 一行(默认折叠)，点开展开成员条目。"""
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = scrollbar.value() if scrollbar is not None else None
        groups = self.owner.store.get_aggregation_torrent_groups(agg_id)
        # 一次查询获取全部成员条目，按 torrent_hash 分组
        all_members = self.owner.store.get_all_aggregation_torrent_items(agg_id)
        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        total = sum(g.get("count") or 0 for g in groups)
        self._agg_group_rows = {}
        self._head_by_member = {}
        for g in groups:
            head_hash = g.get("hash") or ""
            head_title = (g.get("title") or "(无标题)")
            srcs = g.get("feed_count") or 0
            group_item = QtWidgets.QListWidgetItem()
            group_item.setData(QtCore.Qt.UserRole, f"__agg_head__{head_hash}")
            group_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            lbl_head = _HeadRow()
            lbl_head.setToolTip(
                "单击标题=预览该分组\n双击=默认打开一个来源\n单击来源徽标=展开查看全部来源")
            lbl_head.setText(head_title)
            lbl_head.set_count("{} 来源".format(srcs))
            _hc = _rss_colors()
            lbl_head.setStyleSheet(
                "QPushButton#rssHeadTitle { text-align:left; border:none; background:transparent; "
                f"color:{_hc['title_unread']}; padding:2px; }}"
                f"QPushButton#rssHeadCount {{ background:{_hc['badge_bg']}; color:{_hc['badge_fg']}; "
                "border-radius:9px; padding:2px 9px; font-size:12px; font-weight:600; }"
                f"QPushButton#rssHeadTitle:hover {{ color:{_hc['accent']}; }}"
            )
            lbl_head.titleClicked.connect(
                lambda _=False, h=head_hash, agg=agg_id: self._agg_head_preview(h, agg))
            lbl_head.badgeClicked.connect(
                lambda _=False, h=head_hash: self._toggle_torrent_group(h))
            lbl_head.headDoubleClicked.connect(
                lambda _=False, h=head_hash, agg=agg_id: self._agg_head_open(h, agg))
            lbl_head.checkboxToggled.connect(
                lambda checked, h=head_hash: self._on_head_checkbox_toggled(h, checked))
            self.item_list.addItem(group_item)
            self.item_list.setItemWidget(group_item, lbl_head)
            self._node_item_by_head[head_hash] = group_item
            self._head_buttons[head_hash] = lbl_head
            self._group_children[head_hash] = []

            members = all_members.get(head_hash, [])
            for it in members:
                row_widget, title_btn, chk = _make_item_row(
                    self.item_list, it, None, checked=it["hash"] in self._selected_hashes)
                title_btn.clicked.connect(lambda _=False, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
                chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))
                chk.toggled.connect(
                    lambda _checked, h=head_hash: self._sync_head_checkbox_state(h))
                self._item_title_btns[it["hash"]] = title_btn
                self._item_checkboxes[it["hash"]] = chk
                self._head_by_member[it["hash"]] = head_hash
                citem = QtWidgets.QListWidgetItem()
                citem.setData(QtCore.Qt.UserRole, it["hash"])
                citem.setData(QtCore.Qt.UserRole + 1, it["link"])
                citem.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
                citem.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
                self.item_list.addItem(citem)
                self.item_list.setItemWidget(citem, row_widget)
                self.item_list.setRowHidden(self.item_list.row(citem), True)
                self._group_children[head_hash].append(citem)
            self._sync_head_checkbox_state(head_hash)

        self.lb_page.setText("第 1 页")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)
        self.lb_total.setText("磁链聚合 ◈ {} 个分组 · 共 {} 条".format(len(groups), total))
        QtCore.QTimer.singleShot(0, self._sync_row_heights)
        if prev_value is not None:
            scrollbar.setValue(min(prev_value, scrollbar.maximum()))

    def _agg_head_preview(self, head_hash, agg_id):
        """单击聚合头标题：预览该分组默认(最相关)的一个来源。"""
        it = self._pick_group_item(agg_id, head_hash)
        if it is None:
            return
        self.owner.store.mark_read(it["hash"])
        self._update_read_appearance(it["hash"], True)
        self._show_preview_by_hash(it["hash"], it["link"])

    def _agg_head_open(self, head_hash, agg_id):
        """双击聚合头：默认找一个来源并在系统浏览器打开。"""
        it = self._pick_group_item(agg_id, head_hash)
        if it is None:
            return
        link = it["link"]
        webbrowser.open(link)
        if it["hash"]:
            self.owner.store.mark_read(it["hash"])
            self._update_read_appearance(it["hash"], True)

    def _pick_group_item(self, agg_id, head_hash):
        """从分组里挑一个默认来源：优先已读次数少/内容更全的，否则取最近一条。"""
        try:
            members = self.owner.store.get_aggregation_torrent_items(agg_id, head_hash)
        except Exception:
            members = []
        if not members:
            return None
        for it in members:
            if it.get("link") and it["link"].lower().startswith(("magnet:", "http")):
                return it
        return members[0]

    def _toggle_torrent_group(self, head_hash):
        group_item = self._group_children.get(head_hash)
        if group_item is None:
            return
        hidden = self.item_list.isRowHidden(self.item_list.row(group_item[0]))
        for citem in group_item:
            self.item_list.setRowHidden(self.item_list.row(citem), not hidden)
        btn = self._head_buttons.get(head_hash)
        if btn is not None:
            txt = btn.text()
            # 折叠(▸/指向右) <-> 展开(▾/指向下)；用统一记号开头，避免重复前缀
            txt = txt.lstrip("▸ ▾ ▹ ▿ ")
            if hidden:
                btn.setText("▾ " + txt)
            else:
                btn.setText("▸ " + txt)
        QtCore.QTimer.singleShot(0, self._sync_row_heights)

    def _on_head_checkbox_toggled(self, head_hash, checked):
        members = self._group_children.get(head_hash, [])
        for citem in members:
            h = citem.data(QtCore.Qt.UserRole)
            chk = self._item_checkboxes.get(h)
            if chk is not None:
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
                if checked:
                    self._selected_hashes.add(h)
                else:
                    self._selected_hashes.discard(h)
        self._update_batch_buttons()

    def _sync_head_checkbox_state(self, head_hash):
        btn = self._head_buttons.get(head_hash)
        if btn is None:
            return
        members = self._group_children.get(head_hash, [])
        if not members:
            btn.set_check_state(QtCore.Qt.Unchecked)
            return
        checked_count = 0
        total = len(members)
        valid = []
        for citem in members:
            try:
                h = citem.data(QtCore.Qt.UserRole)
            except RuntimeError:
                continue  # 条目已随列表重建被销毁，跳过
            valid.append(citem)
            chk = self._item_checkboxes.get(h)
            if chk is not None and chk.isChecked():
                checked_count += 1
        total = len(valid)
        if checked_count == 0:
            btn.set_check_state(QtCore.Qt.Unchecked)
        elif checked_count == total:
            btn.set_check_state(QtCore.Qt.Checked)
        else:
            btn.set_check_state(QtCore.Qt.PartiallyChecked)

    def _open_aggregation(self, agg_id):
        agg = self.owner.store.get_aggregation(agg_id)
        if not agg:
            return
        # 折叠的磁链聚合：直接展开加载内容
        if agg.get("agg_type") == "torrent":
            self._load_torrent_aggregation(agg_id)
        else:
            self._load_items()

    def _show_add_feed(self):
        self._toggle_feed_section()

    def _show_add_aggregation(self):
        dlg = _AddAggregationDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._reload_sidebar()
            self.on_sidebar_selection_changed()

    def _show_edit_aggregation(self, agg_id):
        dlg = _AddAggregationDialog(self.owner, self, agg_id=agg_id)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._reload_sidebar()
            self.on_sidebar_selection_changed()

    def _on_title_click(self, item_hash, link):
        self.owner.store.mark_read(item_hash)
        self._update_read_appearance(item_hash, True)
        self._show_preview_by_hash(item_hash, link)

    def _on_check_toggled(self, item_hash, checked):
        if checked:
            self._selected_hashes.add(item_hash)
        else:
            self._selected_hashes.discard(item_hash)
        self._update_batch_buttons()

    def _on_item_changed(self, item):
        pass

    def _on_item_clicked(self, item):
        h = item.data(QtCore.Qt.UserRole)
        if isinstance(h, str) and h.startswith("__agg_head__"):
            return  # 聚合头点击由头部自身的标题/徽标事件负责
        link = item.data(QtCore.Qt.UserRole + 1)
        if h:
            self.owner.store.mark_read(h)
            self._update_read_appearance(h, True)
        self._show_preview(item)
        self._last_clicked_row = self.item_list.row(item)

    def _update_read_appearance(self, item_hash, is_read):
        btn = self._item_title_btns.get(item_hash)
        if btn is not None:
            c = _rss_colors()
            dot = getattr(btn, "_rss_dot", None)
            if dot is not None:
                dot.setStyleSheet(
                    f"QLabel {{ color: {c['dot_unread' if not is_read else 'dot_read']}; font-size: 10px; }}")
            if is_read:
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; border: none; background: transparent; "
                    f"color: {c['title_read']}; padding: 2px; }}"
                    f"QPushButton:hover {{ color: {c['text_secondary']}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; border: none; background: transparent; color: {c['title_unread']}; "
                    "font-weight: 600; padding: 2px; }"
                    f"QPushButton:hover {{ color: {c['accent']}; }}"
                )

    def _show_preview(self, item):
        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)
        img_url = item.data(QtCore.Qt.UserRole + 3)
        if not h:
            return
        item_data = self.owner.store.get_item(h)
        if not item_data:
            return
        if img_url and not item_data.get("image_url"):
            item_data = dict(item_data)
            item_data["image_url"] = img_url
        self._preview_link = link
        self._display_preview(item_data, link)

    def _show_preview_by_hash(self, item_hash, link):
        item_data = self.owner.store.get_item(item_hash)
        if not item_data:
            return
        self._preview_link = link
        self._display_preview(item_data, link)

    @staticmethod
    def _nudge_frameless(view):
        """WebEngine 子窗口挂入无边框窗口后重刷 DWM 效果。

        根因：原实现调用 win.updateFrameless()，其内部 setWindowFlags()
        会对已可见的原生窗口触发隐式隐藏（Qt setParent 副作用），
        导致 RSS 模块窗口在打开 WebEngine 预览时"直接关闭"
        （进程仍存活、无崩溃日志）。
        这里只重刷 DWM 阴影/动画效果（updateFrameless 的有效部分），
        不触碰 windowFlags，窗口不会被隐藏重建。
        """
        try:
            win = view.window()
            if win is None:
                return
            we = getattr(win, "windowEffect", None)
            if we is None:
                return
            try:
                we.addWindowAnimation(win.winId())
            except Exception:
                pass
            from qframelesswindow import AcrylicWindow
            if not isinstance(win, AcrylicWindow):
                try:
                    we.addShadowEffect(win.winId())
                except Exception:
                    pass
        except Exception:
            pass

    def _ensure_preview_web(self):
        """惰性创建/复用 WebEngine 预览（全局常驻单例，首次展示才构造）。
        视图/页面/Profile 会持续存活到模块窗口关闭，避免反复创建销毁触发
        WebEngine 的 GC 崩溃。不可用时回退为 QTextBrowser 文本模式。

        渲染进程死亡（renderProcessTerminated）后，render_process_alive 标记
        为 False，后续点击直接回退文本预览，不再重建 WebEngine——旧代码在
        _on_terminated 清除 _PREVIEW_KEEP["view"]，导致下次点击重新创建
        QWebEngineProfile → 新 Chromium 子进程 → 又崩 → 线程无限增长。"""
        # 已有本地引用：检查渲染进程是否仍存活
        if self._preview_browser_view is not None:
            if _PREVIEW_KEEP.get("render_process_alive", True):
                return self._preview_browser_view
            # 渲染进程已死，清理本地引用，回退文本
            self._preview_browser_view = None
            self.preview_browser = None
        # 尝试复用全局常驻视图
        kept = _PREVIEW_KEEP["view"]
        if kept is not None and _PREVIEW_KEEP.get("render_process_alive", True):
            try:
                kept.windowTitle()
                _ = kept.isVisible()
                # parent=None 表示视图已被摘除（上一个模块窗口销毁时），允许复用
                # parent=self._preview_stack 表示已在当前面板中，允许复用
                # 其他情况说明 C++ 对象被别的窗口持有，不可复用
                p = kept.parent()
                if p is not None and p is not self._preview_stack:
                    raise RuntimeError("parent mismatch")
            except RuntimeError:
                kept = None
        if kept is None:
            # 渲染进程已崩溃：不再创建新的 QWebEngineProfile/View，
            # 每次创建都会拉起独立 Chromium 子进程 → 线程无限增长。
            if not _PREVIEW_KEEP.get("render_process_alive", True):
                logger.warning("WebEngine 渲染进程已崩溃，预览回退到内置阅读视图")
                self._preview_web_ok = False
                return self._ensure_text_preview()
            with timed("rss.open.webengine"):
                view, ok = _make_preview_view(self)
            if view is None:
                logger.warning("WebEngine 不可用，预览回退到内置阅读视图")
                self._preview_web_ok = False
                return self._ensure_text_preview()
            view.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
            self._preview_stack.addWidget(view)
            _lf = getattr(view, "loadFinished", None)
            if _lf is not None:
                _lf.connect(self._on_preview_load_finished)
            self._nudge_frameless(view)
            self._preview_browser_view = view
            self.preview_browser = view
            self._preview_web_ok = ok
            logger.info("WebEngine 预览挂入面板 stack_idx=%s",
                        self._preview_stack.indexOf(view))
            return view
        logger.info("WebEngine 预览复用已存在的视图（不重建）")
        self._preview_web_ok = True
        kept.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        if kept.parent() is not self._preview_stack:
            self._preview_stack.addWidget(kept)
        self._nudge_frameless(kept)
        self._preview_browser_view = kept
        self.preview_browser = kept
        return kept

    def _ensure_text_preview(self):
        """安全文本预览视图（QTextBrowser，外链走系统浏览器），永不崩溃。"""
        if self._preview_text_view is None:
            tb = QtWidgets.QTextBrowser()
            tb.setOpenExternalLinks(True)
            tb.setPlaceholderText("点击条目可在此预览内容...")
            tb.setStyleSheet(
                ("QTextBrowser {{ background: {panel}; border: none; border-radius: 8px; }}").format(**_rss_colors())
            )
            self._preview_text_view = tb
            self._preview_stack.addWidget(tb)
            self.preview_browser = tb
        return self._preview_text_view

    def _display_preview(self, item_data, link):
        """默认在 WebEngine 预览中加载文章原文；仅当 rss.web_preview=false
        时才退回内置阅读视图（规避个别机器上的 WebEngine GC 崩溃）。"""
        title = item_data.get("title", "")
        desc = item_data.get("description", "")
        self._set_summary(item_data)
        self._preview_link = link
        web_enabled = bool(self.owner.context.config.get("rss.web_preview", True))
        if web_enabled and link and link.startswith("http"):
            view = self._ensure_preview_web()
            if self._preview_web_ok:
                self._preview_stack.setCurrentWidget(view)
                url = link[:120]
                logger.info("预览加载原文 web=%s", url)
                self._preview_fallback = (title, desc, link, item_data)
                self._preview_pending = link
                self._preview_timer.start()
                return
        logger.debug("预览使用内置阅读视图 link=%s", (link or "")[:120])
        html = self._summary_html(title, desc, link, item_data)
        view = self._ensure_text_preview()
        self._preview_stack.setCurrentWidget(view)
        view.setHtml(html)

    def _preview_do_load(self):
        """去抖后真正发起唯一一次 WebEngine 加载；先 stop() 取消在途导航。"""
        link = self._preview_pending
        self._preview_pending = None
        view = self._preview_browser_view
        if not link or view is None:
            return
        try:
            view.stop()
        except Exception:
            pass
        try:
            view.load(QtCore.QUrl(link))
        except Exception as e:  # pragma: no cover
            logger.warning("WebEngine 加载异常，回退内置阅读视图: %s", e)
            self._preview_fallback_text()

    # noinspection PyUnusedLocal
    def _on_preview_load_finished(self, ok):
        """加载失败时自动回退到内置阅读视图，避免用户对着白屏。"""
        if ok:
            return
        if self.sender() is not self._preview_browser_view:
            return
        self._preview_fallback_text()

    def _preview_fallback_text(self):
        fb = self._preview_fallback
        if fb is None:
            return
        html = self._summary_html(fb[0], fb[1], fb[2], fb[3])
        view = self._ensure_text_preview()
        self._preview_stack.setCurrentWidget(view)
        view.setHtml(html)
        logger.warning("原文加载失败，已回退内置阅读视图")

    def _set_summary(self, item_data):
        title = (item_data or {}).get("title", "").strip()
        self._summary_title.setText(title or "（无标题）")
        meta_parts = []
        source = (item_data or {}).get("tags", "")
        published = (item_data or {}).get("published", "")
        if source:
            meta_parts.append("标签: {}".format(source))
        if published:
            meta_parts.append("更新时间: {}".format(published))
        self._summary_meta.setText("   ·  ".join(meta_parts))
        plain = re.sub(r"<[^>]+>", " ", (item_data or {}).get("description", "") or "")
        plain = re.sub(r"\s+", " ", plain).strip()
        self._summary_desc.setText(plain[:400] + ("…" if len(plain) > 400 else ""))

    def _summary_html(self, title, desc, link, item_data=None):
        img_url = (item_data or {}).get("image_url", "")
        published = (item_data or {}).get("published", "")
        source = (item_data or {}).get("tags", "")
        c = _rss_colors()
        if c["dark"]:
            bg, fg, sec, faint = "#1e1f22", "#e8e8e8", "#9a9a9a", "#76767a"
            pre_bg, quote_line, border = "rgba(255,255,255,0.06)", "rgba(255,255,255,0.18)", "rgba(255,255,255,0.16)"
            accent = "#5aa6ff"
        else:
            bg, fg, sec, faint = "#ffffff", "#1f1f1f", "#666666", "#999999"
            pre_bg, quote_line, border = "#f6f8fa", "#e0e0e0", "#dddddd"
            accent = "#1967d2"
        css = (
            f"body{{font-family:Segoe UI,Microsoft YaHei,sans-serif;color:{fg};line-height:1.7;"
            f"margin:0;padding:20px;background:{bg};}}"
            f"h3{{margin-top:0;}} .meta{{color:{sec};font-size:12px;}}"
            f"img{{max-width:100%;border-radius:4px;}} a{{color:{accent};}}"
            f"pre{{background:{pre_bg};padding:10px;border-radius:6px;overflow:auto;}}"
            f"blockquote{{border-left:4px solid {quote_line};margin-left:0;padding-left:14px;color:{sec};}}"
            f"table{{border-collapse:collapse;width:100%;}} th,td{{border:1px solid {border};padding:6px 10px;}}"
        )
        parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>"]
        parts.append(f"<h3>{self._esc(title)}</h3>")
        meta = []
        if source:
            meta.append(f"<span class='meta' style='color:{accent};'>标签: {self._esc(source)}</span>")
        if published:
            meta.append(f"<span class='meta'>更新时间: {self._esc(published)}</span>")
        if meta:
            parts.append("<p>" + " &nbsp; ".join(meta) + "</p>")
        if img_url and img_url.startswith("http"):
            parts.append(f"<p><img src='{self._esc(img_url)}' alt='' loading='lazy'></p>")
        if desc:
            parts.append("<hr><div>" + _sanitize_html(desc) + "</div>")
        if link:
            parts.append(f"<hr><p><b>原文链接:</b> <a href='{self._esc(link)}'>{self._esc(link)}</a>"
                         f"<span style='color:{faint};font-size:12px;'>（点击页内链接将用系统浏览器打开）</span></p>")
        parts.append("</body></html>")
        return "".join(parts)

    @staticmethod
    def _esc(s):
        import html as _html_mod
        return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        h = item.data(QtCore.Qt.UserRole)
        if isinstance(h, str) and h.startswith("__agg_head__"):
            return  # 聚合头双击由头部自身处理
        if link:
            self.owner.store.mark_read(h)
            self._update_read_appearance(h, True)
            self._show_preview(item)

    def _select_all(self, state):
        checked = state == QtCore.Qt.CheckState.Checked.value
        sel = self._sidebar.current_filter() if hasattr(self, "_sidebar") else {}
        if sel.get("agg_type") == "torrent":
            # 磁链分组：成员复选框已全部存在（含折叠隐藏的），直接遍历复选框
            for item_hash, chk in self._item_checkboxes.items():
                chk.setChecked(checked)
        else:
            # 普通列表：跨页全选整个查询结果集
            for it in self._all_items:
                if checked:
                    self._selected_hashes.add(it["hash"])
                else:
                    self._selected_hashes.discard(it["hash"])
            # 同步当前页可见的复选框（阻断信号，避免重复更新集合）
            for item_hash, chk in self._item_checkboxes.items():
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
        for head_hash in self._group_children:
            self._sync_head_checkbox_state(head_hash)
        self._update_batch_buttons()

    def _get_selected_hashes(self):
        return list(self._selected_hashes)

    def _update_batch_buttons(self):
        count = len(self._selected_hashes)
        for key in ("read", "unread", "delete"):
            self._batch_actions[key].setEnabled(count > 0)
        self.btn_batch_ops.setText(f"批量操作 ({count})" if count else "批量操作")

    def _batch_mark_read(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_read(hashes)
            for h in hashes:
                self._update_read_appearance(h, True)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_mark_unread(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_unread(hashes)
            for h in hashes:
                self._update_read_appearance(h, False)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_delete(self):
        hashes = self._get_selected_hashes()
        if hashes:
            reply = QtWidgets.QMessageBox.question(
                self, "确认删除", f"确定删除 {len(hashes)} 条记录？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.owner.store.batch_delete(hashes)
                self._selected_hashes.clear()
                self._load_items()

    def _mark_all_read(self):
        tag_filter = self.combo_tag.currentData()
        self.owner.store.mark_all_read(tag_filter)
        self._load_items(preserve_scroll=True)

    def _show_context_menu(self, pos):
        item = self.item_list.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)

        act_open = menu.addAction("打开链接")
        act_preview = menu.addAction("预览详情")
        act_copy = menu.addAction("复制链接")
        act_share = menu.addAction("分享到剪贴板")
        menu.addSeparator()
        act_read = menu.addAction("标记已读")
        act_unread = menu.addAction("标记未读")
        menu.addSeparator()
        act_fav = menu.addAction("收藏/取消收藏")
        menu.addSeparator()

        categories = self.owner.store.get_categories()
        if categories:
            cat_menu = menu.addMenu("添加到分类")
            for cat in categories:
                act = cat_menu.addAction(f"{cat['name']}")
                act.setData(cat["id"])

        action = menu.exec_(self.item_list.mapToGlobal(pos))
        if not action:
            return

        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)

        if action == act_open:
            if link:
                webbrowser.open(link)
        elif action == act_preview:
            self._show_preview(item)
        elif action == act_copy:
            if link:
                QtWidgets.QApplication.clipboard().setText(link)
        elif action == act_share:
            text = self.owner.store.share_item(h)
            if text:
                QtWidgets.QApplication.clipboard().setText(text)
                self.lb_status.setText("已复制到剪贴板")
        elif action == act_read:
            self.owner.store.mark_read(h)
            self._load_items()
        elif action == act_unread:
            self.owner.store.mark_unread(h)
            self._load_items()
        elif action == act_fav:
            self.owner.store.toggle_favorite(h)
            self._load_items()
        elif hasattr(action, "data") and action.data():
            cat_id = action.data()
            self.owner.store.set_item_category(h, cat_id)

    def _export_opml(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出 OPML", "subscriptions.opml", "OPML Files (*.opml)")
        if path:
            try:
                export_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导出到 {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _import_opml(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入 OPML", "", "OPML Files (*.opml);;All Files (*)")
        if path:
            try:
                count = import_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导入 {count} 个订阅源")
                self._load_feeds()
                self._load_tag_filter()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _save_proxy(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner._proxy = proxy

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.context.config.set("rss.cleanup_days", days)
        self.owner.store.cleanup_old(days)
        self._load_items()
        QtWidgets.QMessageBox.information(self, "完成", f"已清理 {days} 天前的数据")

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            item = QtWidgets.QListWidgetItem(f"{kw['keyword']} ({kw['color']})")
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if item:
            kid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_keyword(kid)
            self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for rule in self.owner.store.get_filter_rules():
            status = "✓" if rule["enabled"] else "✗"
            text = f"{status} {rule['name']}: {rule['field']} {rule['operator']} '{rule['value']}' → {rule['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, rule["id"])
            item.setData(QtCore.Qt.UserRole + 1, rule["enabled"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_filter_rule(rid)
            self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            enabled = item.data(QtCore.Qt.UserRole + 1)
            self.owner.store.update_filter_rule(rid, enabled=not enabled)
            self._load_rules()

    def _load_categories(self):
        self.category_list.clear()
        for cat in self.owner.store.get_categories():
            item = QtWidgets.QListWidgetItem(f"{cat['name']} ({cat['color']})")
            item.setData(QtCore.Qt.UserRole, cat["id"])
            item.setData(QtCore.Qt.UserRole + 1, cat)
            self.category_list.addItem(item)

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if item:
            cat = item.data(QtCore.Qt.UserRole + 1)
            dlg = _CategoryDialog(self.owner, self, category=cat)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if item:
            cid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_category(cid)
            self._load_categories()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(20):
            text = f"[{h['read_at']}] {h['title']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        stats = self.owner.store.get_feed_stats()
        total_items = self.owner.store.get_item_count()
        total_unread = self.owner.store.get_unread_count()
        lines = [f"总条目: {total_items}", f"未读: {total_unread}", ""]
        for s in stats:
            lines.append(f"{s['name']}: {s['total']}条 (未读:{s['unread']})")
        self.lb_stats.setText("\n".join(lines))
