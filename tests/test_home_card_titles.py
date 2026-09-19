"""主页卡片标题去重测试。

背景（AGENTS.md 增量迁移 + 主页问题3）：
卡片级标题由 ui/home_tab/tab_layout.py::_create_card 统一渲染
（StrongBodyLabel(mod.name) + hover ✕ 关闭按钮），每个卡片有且仅有一个标题。
因此模块内层 home widget **不得**再自绘与模块名相同的标题文本，
否则卡片左上角会出现两个标题。

本测试锁定 5 个曾自绘同名标题的模块：
rss_aggregator / todo_notes / webview_control / win_maintenance / path_forward。
"""
import pytest
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _FakeConfig(dict):
    def __init__(self):
        super().__init__()
        self._data = {}

    def get(self, key, default=None):
        return {**self._data, **dict(self)}.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class _FakeCtx:
    def __init__(self):
        self.config = _FakeConfig()


class _OwnerBase:
    """最小 owner 替身：提供各 home widget 引用的属性。"""

    def __init__(self):
        self.context = _FakeCtx()
        self._last_hosts = []
        self._monitor_running = False
        self.blocked = set()
        self.host_log = []
        self._home_refresh = lambda: None

    def refresh_now(self):
        pass

    def scan_hashes(self, limit=200):
        pass

    def refresh_favicons(self):
        pass

    def _on_hotkey(self):
        pass


def _labels(widget):
    return [lb.text() for lb in widget.findChildren(QtWidgets.QLabel)]


def test_rss_home_filter_combo_is_native():
    """主页卡片在 QGraphicsProxyWidget 中渲染，qfluentwidgets ComboBox 的
    RoundMenu（透明无边框 popup + 阴影 + setMask 动画）在该环境下会重影/破碎，
    必须使用原生 QComboBox（make_combo 工厂）的栈层 popup。
    """
    _app()
    owner = _OwnerBase()
    from modules.rss_aggregator.home import _RssHomeWidget
    w = _RssHomeWidget(owner, None)
    try:
        combo = w.combo_filter
        assert isinstance(combo, QtWidgets.QComboBox), (
            f"主页筛选下拉必须是原生 QtWidgets.QComboBox（实际: {type(combo).__name__}）"
            f"，qfluentwidgets ComboBox 在 proxy 环境中弹出菜单会重影/破碎"
        )
        # RoundMenu popup 是 qfluentwidgets ComboBox 专属；原生 QComboBox 无 dropMenu
        assert not hasattr(combo, "dropMenu")
        assert combo.minimumWidth() >= 120, "筛选下拉最小宽度应 >= 120（修复过窄问题）"
        # 接口兼容性：_load_items 依赖 addItem(text, userData) / currentData()
        assert combo.itemData(1) == "unread"
        assert combo.count() == 5
    finally:
        w.close()


@pytest.mark.parametrize(
    "module_id, inner_title",
    [
        ("rss_aggregator", "RSS 聚合"),
        ("todo_notes", "待办事项"),
        ("webview_control", "WebView2 管控"),
        ("win_maintenance", "Windows维护"),
        ("path_forward", "路径传递"),
    ],
)
def test_home_widget_does_not_duplicate_card_title(module_id, inner_title):
    """模块 home widget 内部不得再自绘标题文本（卡片级标题由 _create_card 唯一渲染）。"""
    _app()
    owner = _OwnerBase()

    if module_id == "rss_aggregator":
        from modules.rss_aggregator.home import _RssHomeWidget
        w = _RssHomeWidget(owner, None)
    elif module_id == "todo_notes":
        from modules.todo_notes.home import _make_home_widget
        w = _make_home_widget(owner, None)
    elif module_id == "webview_control":
        from modules.webview_control.home import _make_home_widget
        w = _make_home_widget(owner, None)
    elif module_id == "win_maintenance":
        from modules.win_maintenance.home import _make_home_widget
        w = _make_home_widget(owner, None)
    elif module_id == "path_forward":
        from modules.path_forward import _make_home_widget
        w = _make_home_widget(owner, None)

    try:
        texts = _labels(w)
        assert inner_title not in texts, (
            f"{module_id} home widget 内部仍自绘标题「{inner_title}」，"
            f"会与 tab_layout._create_card 的 StrongBodyLabel(mod.name) 重复。实际文本: {texts}"
        )
    finally:
        w.close()