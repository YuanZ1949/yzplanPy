"""RSS 页面：预览视图（WebEngine/文本回退）。"""

import html, logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from core.perf import timed

from .page_batch import _RssPageWidget
from .preview import _PREVIEW_KEEP
from .text_utils import _rss_colors, _sanitize_html

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

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
                from . import _make_preview_view
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
        c = _rss_colors()
        title = (item_data or {}).get("title", "").strip()
        self._summary_title.setText(title or "（无标题）")

        # status-chip：文章/磁链 pill
        link = (item_data or {}).get("link", "")
        is_torrent = bool(re.search(r"magnet:|torrent|\.torrent", link or "", re.I))
        chip_text = "磁链" if is_torrent else "文章"
        if c["dark"]:
            chip_bg = "rgba(255,107,142,0.16)" if is_torrent else "rgba(37,205,150,0.16)"
            chip_fg = "#ff9ab0" if is_torrent else "#7fe0c0"
        else:
            chip_bg = "#fce8e6" if is_torrent else "#e6f4ea"
            chip_fg = "#c5221f" if is_torrent else "#137333"
        self._summary_status.setText(chip_text)
        self._summary_status.setStyleSheet(
            f"QLabel {{ font-size: 11px; padding: 3px 10px; border-radius: 14px; "
            f"font-weight: 600; background: {chip_bg}; color: {chip_fg}; }}")

        # 结构化 meta
        meta_parts = []
        published = (item_data or {}).get("published", "")
        if published:
            meta_parts.append(f"🕐 {published}")
        source = (item_data or {}).get("feed_name", "") or (item_data or {}).get("tags", "")
        if source:
            meta_parts.append(f"⚙ {source}")
        tags = (item_data or {}).get("tags", "")
        if tags and tags != source:
            meta_parts.append(f"🏷 {tags}")
        self._summary_meta.setText("\n".join(meta_parts))

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
