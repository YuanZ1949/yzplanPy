import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.config import AppConfig
from modules.registry import ModuleContext, ModuleRegistry
from ui.modules_tab import ModulesTab


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _make_tab():
    _app()
    config = AppConfig()
    context = ModuleContext(config=config, host_window=None, app=_app())
    context.registry = ModuleRegistry(context)
    return ModulesTab(context)


def _resize(tab, w):
    """模拟网格容器宽度变化：设置几何 + 向事件过滤器投递合成 Resize 事件。"""
    tab.grid_widget.resize(w, 400)
    ev = QtGui.QResizeEvent(QtCore.QSize(w, 400), QtCore.QSize(tab.grid_widget.width(), 400))
    tab._resize_watcher.eventFilter(tab.grid_widget, ev)


def test_modules_grid_cols_adapt_to_width():
    # 卡片列数随网格宽度自适应：760->4 列，400->2 列，200->1 列
    tab = _make_tab()
    assert tab._calc_cols() >= 1, "初始（未布局）至少 1 列"
    _resize(tab, 760)
    assert tab._cols == 4, f"760 宽应为 4 列，实际 {tab._cols}"
    _resize(tab, 400)
    assert tab._cols == 2, f"400 宽应为 2 列，实际 {tab._cols}"
    _resize(tab, 200)
    assert tab._cols == 1, f"200 宽应为 1 列，实际 {tab._cols}"


def test_modules_grid_rebuilds_only_on_col_change():
    # 列数不变时 resize 不重建；列数变化时重建一次
    tab = _make_tab()
    calls = []
    orig = tab._rebuild

    def counting():
        calls.append(1)
        orig()

    tab._rebuild = counting
    _resize(tab, 760)
    c1 = len(calls)
    assert c1 >= 1, "首次布局应触发重建"
    # 同列数 resize（760 -> 780 仍 4 列）不重建
    _resize(tab, 780)
    assert len(calls) == c1, "列数不变时不应重建"
    # 列数变化（780 -> 400 变 2 列）触发一次重建
    _resize(tab, 400)
    assert len(calls) == c1 + 1, "列数变化应恰好重建一次"


def test_modules_cards_stay_square():
    # 卡片保持 170x170 正方形
    tab = _make_tab()
    _resize(tab, 760)
    assert tab.cards, "应有模块卡片"
    for card in tab.cards:
        assert card.width() == 170 and card.height() == 170