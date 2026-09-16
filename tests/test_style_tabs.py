"""全局 QTabBar/QTabWidget 样式：令牌驱动 + 明暗双主题未选中 tab 可见。

背景：screenshot（5 tab）与 win_maintenance（2 tab）的 QTabWidget 无任何
tab 样式，未选中 tab 文字色与背景同色而不可见；perf_monitor 有私有
_tabs_style 故正常。本测试锁定全局 QSS 必须含令牌驱动的 tab 规则。
"""
import re

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _sheet(dark):
    if dark:
        from core.theme.qss_dark import _apply_dark_sheet
        _apply_dark_sheet(False)
    else:
        from core.theme.qss_light import _apply_light_sheet
        _apply_light_sheet(False)
    return QtWidgets.QApplication.instance().styleSheet()


def test_qss_sheets_have_tab_rules(_qapp):
    """明暗两套全局 QSS 都必须含 QTabBar/QTabWidget 规则（未选中 tab 可见）。"""
    for dark in (True, False):
        s = _sheet(dark)
        for rule in ("QTabWidget::pane", "QTabWidget::tab-bar",
                     "QTabBar::tab", "QTabBar::tab:hover", "QTabBar::tab:selected"):
            assert rule in s, f"{'暗' if dark else '亮'}色 QSS 缺 {rule}"


def test_tab_rules_use_tokens_not_literals(_qapp):
    """tab 规则源码不得含 hex/rgba/px 字面量（颜色/尺寸必须来自令牌）。"""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    for name in ("qss_light.py", "qss_dark.py"):
        text = (repo / "core" / "theme" / name).read_text(encoding="utf-8")
        m = re.search(r"QTabWidget::pane.*?QTabBar::tab:selected.*?\}\}", text, re.S)
        assert m, f"{name} 缺 QTabBar 规则段"
        seg = m.group(0)
        assert not re.search(r"#[0-9a-fA-F]{6}", seg), f"{name} tab 规则含 hex 字面量"
        assert not re.search(r"rgba?\s*\(\s*\d", seg, re.I), f"{name} tab 规则含 rgba 字面量"
        assert not re.search(
            r"(?:padding|margin|width|height|border-radius|font-size|line-height):\s*\d+px", seg), \
            f"{name} tab 规则含裸 px 字面量"


def test_palette_keys_match_both_branches(_qapp):
    """_PALETTE_KEYS 必须与明暗两套调色板 key 集完全一致（双向防漏）。"""
    from core.theme.tokens import theme_palette
    from tests.test_style_tokens import _PALETTE_KEYS
    dark_keys = set(theme_palette(dark=True).keys())
    light_keys = set(theme_palette(dark=False).keys())
    assert dark_keys == light_keys, (
        f"明暗调色板 key 集不一致: 仅暗色={dark_keys - light_keys}, "
        f"仅亮色={light_keys - dark_keys}")
    assert _PALETTE_KEYS == dark_keys, (
        f"_PALETTE_KEYS 与调色板 key 集不一致: "
        f"未登记={dark_keys - _PALETTE_KEYS}, 多余={_PALETTE_KEYS - dark_keys}")