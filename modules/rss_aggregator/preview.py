"""RSS 预览视图工厂：_PREVIEW_KEEP 全局单例与 _make_preview_view。"""

import logging
import os
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")

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
                if typ == QWebEnginePage.NavigationTypeLinkClicked:  # type: ignore[reportAttributeAccessIssue]
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
        js_off = [QWebEngineSettings.JavascriptEnabled, QWebEngineSettings.JavascriptCanOpenWindows,  # type: ignore[reportAttributeAccessIssue]
                  QWebEngineSettings.JavascriptCanAccessClipboard, QWebEngineSettings.JavascriptCanPaste]  # type: ignore[reportAttributeAccessIssue]
        for settings in (profile.settings(), view.settings()):
            for attr in js_off + [QWebEngineSettings.PluginsEnabled, QWebEngineSettings.AllowRunningInsecureContent,  # type: ignore[reportAttributeAccessIssue]
                                  QWebEngineSettings.HyperlinkAuditingEnabled, QWebEngineSettings.WebGLEnabled,  # type: ignore[reportAttributeAccessIssue]
                                  QWebEngineSettings.ScreenCaptureEnabled]:  # type: ignore[reportAttributeAccessIssue]
                settings.setAttribute(attr, False)
            settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)  # type: ignore[reportAttributeAccessIssue]
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
