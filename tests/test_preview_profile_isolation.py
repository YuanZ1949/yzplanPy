"""回归（D14）：RSS 预览禁用 JS 只允许作用于页面级 settings，不得污染
defaultProfile 全局设置。

背景：_make_preview_view 曾同时遍历 (profile.settings(), view.settings())
禁用 JS/插件。profile.settings() 即 QWebEngineProfile.defaultProfile() 的
全局设置，被所有使用 defaultProfile 的视图共享——包括 page_selector 对话框
（dialog_core.py 用 _webengine_view() 创建视图且不覆盖设置）。defaultProfile
全局禁用 JS 后，_PICKER_JS（dialog_actions.py）注入不执行，选择器失效。

本测试为逻辑层单元测试：mock QWebEngineView/QWebEngineProfile，断言
setAttribute 只被调用在 view.settings()（页面级）上，profile.settings()
（defaultProfile 全局）必须保持零触碰。WebEngine 真实渲染无法在无显示
环境运行，故用对象归属断言锁定行为。
"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.rss_aggregator.preview import _PREVIEW_KEEP, _make_preview_view


# ── 假 WebEngine 对象（仅覆盖 _make_preview_view 用到的成员）──────────

class _FakeSettings:
    def __init__(self):
        self.calls = []  # [(attr, value), ...]

    def setAttribute(self, attr, value):
        self.calls.append((attr, value))


class _FakeProfile:
    _default = None

    def __init__(self):
        self._settings = _FakeSettings()

    def settings(self):
        return self._settings

    @classmethod
    def defaultProfile(cls):
        if cls._default is None:
            cls._default = cls()
        return cls._default


class _FakePage:
    NavigationTypeLinkClicked = 0

    def __init__(self, profile):
        self.profile = profile

    def acceptNavigationRequest(self, url, typ, isMainFrame):
        return True


class _FakeSignal:
    def connect(self, slot):
        self.slot = slot


class _FakeView:
    def __init__(self):
        self._settings = _FakeSettings()
        self._page = None
        self.loadStarted = _FakeSignal()
        self.loadFinished = _FakeSignal()
        self.renderProcessTerminated = _FakeSignal()
        self.urlChanged = _FakeSignal()

    def settings(self):
        return self._settings

    def setPage(self, page):
        self._page = page

    def setHtml(self, html):
        pass


class _FakeWebEngineSettings:
    JavascriptEnabled = 1
    JavascriptCanOpenWindows = 2
    JavascriptCanAccessClipboard = 3
    JavascriptCanPaste = 4
    PluginsEnabled = 5
    AllowRunningInsecureContent = 6
    HyperlinkAuditingEnabled = 7
    WebGLEnabled = 8
    ScreenCaptureEnabled = 9
    ErrorPageEnabled = 10


class _FakeWebEngineWidgets:
    QWebEngineView = _FakeView


class _FakeWebEngineCore:
    QWebEngineProfile = _FakeProfile
    QWebEnginePage = _FakePage
    QWebEngineSettings = _FakeWebEngineSettings


_JS_OFF_ATTRS = (
    _FakeWebEngineSettings.JavascriptEnabled,
    _FakeWebEngineSettings.JavascriptCanOpenWindows,
    _FakeWebEngineSettings.JavascriptCanAccessClipboard,
    _FakeWebEngineSettings.JavascriptCanPaste,
)


def _patch_webengine():
    return patch.dict(
        sys.modules,
        {
            "PySide6.QtWebEngineWidgets": _FakeWebEngineWidgets,
            "PySide6.QtWebEngineCore": _FakeWebEngineCore,
        },
    )


def _snapshot_preview_keep():
    return dict(_PREVIEW_KEEP)


def _restore_preview_keep(snap):
    _PREVIEW_KEEP.clear()
    _PREVIEW_KEEP.update(snap)


def test_preview_disables_js_only_on_view_settings_not_profile():
    """defaultProfile 全局设置必须零触碰；页面级 JS 禁用保持不变。"""
    keep_snap = _snapshot_preview_keep()
    _FakeProfile._default = None
    try:
        with _patch_webengine(), patch("core.perf.mark_webengine_alive"):
            view, ok = _make_preview_view()
        assert ok is True
        assert isinstance(view, _FakeView)

        profile_settings = _FakeProfile._default.settings()  # type: ignore[reportAttributeAccessIssue]
        view_settings = view.settings()

        # 关键断言：defaultProfile 全局设置不得被 RSS 预览禁用 JS/插件
        assert profile_settings.calls == [], (  # type: ignore[reportAttributeAccessIssue]
            "defaultProfile 全局设置被污染：RSS 预览不得在 profile.settings() "
            "上禁用 JS/插件（会波及 page_selector 等共享 defaultProfile 的视图）"
        )

        # RSS 预览自身页面级 JS 禁用行为保持不变
        disabled = {attr for attr, _val in view_settings.calls if _val is False}  # type: ignore[reportAttributeAccessIssue]
        assert set(_JS_OFF_ATTRS) <= disabled, (
            "页面级 settings 必须仍禁用 JS（JavascriptEnabled 等）"
        )
        # 错误页仍开启
        assert (_FakeWebEngineSettings.ErrorPageEnabled, True) in view_settings.calls  # type: ignore[reportAttributeAccessIssue]
    finally:
        _restore_preview_keep(keep_snap)
        _FakeProfile._default = None


def test_preview_keeps_plugins_off_at_page_level():
    """插件/危险能力在页面级仍关闭（安全能力不因修复而丢失）。"""
    keep_snap = _snapshot_preview_keep()
    _FakeProfile._default = None
    try:
        with _patch_webengine(), patch("core.perf.mark_webengine_alive"):
            view, ok = _make_preview_view()
        assert ok is True
        view_settings = view.settings()  # type: ignore[reportOptionalMemberAccess]
        disabled = {attr for attr, _val in view_settings.calls if _val is False}  # type: ignore[reportAttributeAccessIssue]
        for attr in (
            _FakeWebEngineSettings.PluginsEnabled,
            _FakeWebEngineSettings.AllowRunningInsecureContent,
            _FakeWebEngineSettings.HyperlinkAuditingEnabled,
            _FakeWebEngineSettings.WebGLEnabled,
            _FakeWebEngineSettings.ScreenCaptureEnabled,
        ):
            assert attr in disabled, f"页面级 settings 必须禁用 attr={attr}"
    finally:
        _restore_preview_keep(keep_snap)
        _FakeProfile._default = None