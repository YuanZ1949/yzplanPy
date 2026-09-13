"""页面选择器（page_selector）对话框测试。

离屏运行（QT_QPA_PLATFORM=offscreen），用替身 WebView 规避真实 QtWebEngine 依赖：
- PageSelectorDialog 可实例化（mock _webengine_view）
- _PICKER_JS 注入逻辑（_on_loaded / _pick / _start_keyword）
- JS 执行回调 _read_result 对选中结果的解析（多选/单选/空结果/关键词过滤分支）
- _current_options / _js_quote / _sync_mode_buttons 纯逻辑
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


# ── 替身 WebView ─────────────────────────────────────────

class _FakePage:
    """记录 runJavaScript 调用。"""

    def __init__(self):
        self.js_calls = []

    def runJavaScript(self, js, callback=None):
        self.js_calls.append(js)
        if callback:
            callback(None)


class _FakeWebView(QtWidgets.QWidget):
    """最小化 QWebEngineView 替身：记录 load / runJavaScript。"""

    loadFinished = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = _FakePage()
        self.loaded = []

    def load(self, url):
        self.loaded.append(url)

    def page(self):
        return self._page


def _make_dialog(url="https://example.com", initial_options=None,
                 view_cls: "type[_FakeWebView] | None" = _FakeWebView):
    """构造 PageSelectorDialog，mock 掉 _webengine_view 避免真实 WebEngine。

    view_cls=None 表示 WebEngine 不可用（走错误提示分支）。
    """
    with patch("modules.page_selector.dialog_core._webengine_view", return_value=view_cls):
        from modules.page_selector.dialog_actions import PageSelectorDialog
        return PageSelectorDialog(url, initial_options=initial_options)


# ── 实例化 ───────────────────────────────────────────────

def test_dialog_constructs_with_mock_webengine():
    """mock WebView 下对话框可完整构建，URL 被加载。"""
    dlg = _make_dialog("https://example.com")
    try:
        assert dlg._webengine_error is False
        assert isinstance(dlg.web, _FakeWebView)
        assert dlg.in_url.text() == "https://example.com"
        assert len(dlg.web.loaded) == 1
        assert dlg.web.loaded[0].toString() == "https://example.com"
        # 关键控件存在
        for attr in ("btn_single", "btn_list", "btn_multi", "btn_multi_gen",
                     "kw_input", "selector_input", "mode_label", "lb_count"):
            assert hasattr(dlg, attr), f"缺少控件 {attr}"
    finally:
        dlg.hide()


def test_dialog_fallback_when_webengine_unavailable():
    """WebEngine 不可用（_webengine_view 返回 None）→ 走错误提示分支。"""
    dlg = _make_dialog("https://example.com", view_cls=None)
    try:
        assert dlg._webengine_error is True
    finally:
        dlg.hide()


def test_dialog_initial_options_preserved():
    """initial_options 传入后进入 _options 与 _last_selector。"""
    dlg = _make_dialog("https://example.com", initial_options={"mode": "list", "selector": "div.a"})
    try:
        assert dlg._options == {"mode": "list", "selector": "div.a"}
        assert dlg._last_selector == "div.a"
        assert dlg.selector_input.text() == "div.a"
    finally:
        dlg.hide()


# ── _PICKER_JS 注入 ──────────────────────────────────────

def test_picker_js_contains_key_markers():
    """_PICKER_JS 包含点选/多选/关键词/结果读取的关键 API。"""
    from modules.page_selector.picker_js import _PICKER_JS
    for marker in ("__yzTogglePickMode", "__yzFinalizeMulti", "__yzMultiCount",
                   "__yzStart", "__yzStop", "__yzResult", "__yzDone"):
        assert marker in _PICKER_JS, f"_PICKER_JS 缺少 {marker}"


def test_on_loaded_injects_picker_js():
    """页面加载完成后注入 _PICKER_JS。"""
    dlg = _make_dialog()
    try:
        from modules.page_selector.picker_js import _PICKER_JS
        dlg._on_loaded(True)
        assert _PICKER_JS in dlg.web._page.js_calls
    finally:
        dlg.hide()


def test_pick_single_injects_js():
    """单元素模式注入 __yzTogglePickMode(\"single\", \"\")。"""
    dlg = _make_dialog()
    try:
        dlg._pick("single")
        assert any("__yzTogglePickMode(\"single\", \"\")" in js for js in dlg.web._page.js_calls)
    finally:
        dlg.hide()


def test_pick_multi_shows_generate_button():
    """多选模式显示「生成多选」按钮并注入 multi 模式 JS。"""
    dlg = _make_dialog()
    try:
        dlg._pick("multi")
        assert not dlg.btn_multi_gen.isHidden()
        assert dlg.btn_multi.isChecked()
        assert any("__yzTogglePickMode(\"multi\", \"\")" in js for js in dlg.web._page.js_calls)
    finally:
        dlg.hide()


def test_start_keyword_injects_js():
    """关键词模式注入带关键词的 JS（含转义）。"""
    dlg = _make_dialog()
    try:
        dlg.kw_input.setText("AI 新闻")
        dlg._start_keyword()
        assert any("__yzTogglePickMode(\"keyword\", \"AI 新闻\")" in js for js in dlg.web._page.js_calls)
    finally:
        dlg.hide()


# ── _read_result：JS 回调结果解析 ────────────────────────

def test_read_result_empty_noop():
    """空结果 / None → 无状态变化。"""
    dlg = _make_dialog()
    try:
        dlg._read_result(None)
        dlg._read_result("")
        assert dlg._last_selector == ""
        assert dlg.selector_input.text() == ""
        assert dlg._options == {}
    finally:
        dlg.hide()


def test_read_result_invalid_json_noop():
    """非法 JSON → 无状态变化。"""
    dlg = _make_dialog()
    try:
        dlg._read_result("not-json{{{")
        assert dlg._last_selector == ""
        assert dlg._options == {}
    finally:
        dlg.hide()


def test_read_result_single_done():
    """单选完成：锁定选择器、同步模式按钮、停止轮询。"""
    dlg = _make_dialog()
    try:
        dlg._read_result('{"done": true, "mode": "single", "selector": "div.a"}')
        assert dlg._last_selector == "div.a"
        assert dlg.selector_input.text() == "div.a"
        assert dlg._options == {"mode": "single", "selector": "div.a"}
        assert dlg.btn_single.isChecked()
        assert not dlg.btn_list.isChecked()
        assert not dlg.btn_multi.isChecked()
        assert dlg.btn_multi_gen.isHidden()
        assert dlg._poll is None  # 已停止轮询
    finally:
        dlg.hide()


def test_read_result_list_done():
    """列表容器完成：mode=list，模式标签显示「列表」。"""
    dlg = _make_dialog()
    try:
        dlg._read_result('{"done": true, "mode": "list", "selector": "ul.items > li"}')
        assert dlg._options == {"mode": "list", "selector": "ul.items > li"}
        assert dlg.btn_list.isChecked()
        assert "列表" in dlg.mode_label.text()
    finally:
        dlg.hide()


def test_read_result_multi_count_update():
    """多选进行中：仅更新已选计数，不锁定。"""
    dlg = _make_dialog()
    try:
        dlg.btn_multi.setChecked(True)
        dlg._read_result('{"multiCount": 3}')
        assert dlg.lb_multi_count.text() == "已选 3 个"
        assert dlg._last_selector == ""  # 未 done，不锁定
    finally:
        dlg.hide()


def test_read_result_done_no_selector_no_lock():
    """done 但 selector 为空 → 不锁定。"""
    dlg = _make_dialog()
    try:
        dlg._read_result('{"done": true, "mode": "single", "selector": ""}')
        assert dlg._last_selector == ""
        assert dlg._options == {}
    finally:
        dlg.hide()


# ── _current_options：模式/选择器汇总 ────────────────────

def test_current_options_default_single():
    """无按钮选中 → 默认 single。"""
    dlg = _make_dialog()
    try:
        assert dlg._current_options() == {"mode": "single", "selector": ""}
    finally:
        dlg.hide()


def test_current_options_list_checked():
    """列表容器按钮选中 → mode=list。"""
    dlg = _make_dialog()
    try:
        dlg.btn_list.setChecked(True)
        dlg.selector_input.setText("ul.items")
        assert dlg._current_options() == {"mode": "list", "selector": "ul.items"}
    finally:
        dlg.hide()


def test_current_options_multi_with_selector():
    """多选按钮选中且有选择器 → mode=list。"""
    dlg = _make_dialog()
    try:
        dlg.btn_multi.setChecked(True)
        dlg.selector_input.setText("div.a")
        assert dlg._current_options() == {"mode": "list", "selector": "div.a"}
    finally:
        dlg.hide()


# ── _js_quote：JS 字符串转义 ─────────────────────────────

def test_js_quote_escapes_quotes_and_backslashes():
    """引号与反斜杠被转义。"""
    dlg = _make_dialog()
    try:
        assert dlg._js_quote('a"b\\c') == '"a\\"b\\\\c"'
        assert dlg._js_quote("plain") == '"plain"'
    finally:
        dlg.hide()


# ── _sync_mode_buttons ───────────────────────────────────

def test_sync_mode_buttons_single():
    """同步到 single：仅单元素按钮选中，生成多选隐藏。"""
    dlg = _make_dialog()
    try:
        dlg.btn_list.setChecked(True)
        dlg.btn_multi.setChecked(True)
        dlg._sync_mode_buttons("single")
        assert dlg.btn_single.isChecked()
        assert not dlg.btn_list.isChecked()
        assert not dlg.btn_multi.isChecked()
        assert dlg.btn_multi_gen.isHidden()
    finally:
        dlg.hide()


def test_sync_mode_buttons_list():
    """同步到 list：仅列表容器按钮选中。"""
    dlg = _make_dialog()
    try:
        dlg._sync_mode_buttons("list")
        assert dlg.btn_list.isChecked()
        assert not dlg.btn_single.isChecked()
    finally:
        dlg.hide()


# ── 导入路径一致性 ───────────────────────────────────────

def test_dialog_actions_import_matches_package_export():
    """dialog_actions 直接导入与包级导出是同一个类（修复目标路径正确）。"""
    from modules.page_selector import PageSelectorDialog as via_pkg
    from modules.page_selector.dialog_actions import PageSelectorDialog as via_actions
    assert via_pkg is via_actions