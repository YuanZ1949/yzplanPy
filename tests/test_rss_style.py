"""RSS 样式回归测试：标题栏迁移按钮 QSS 含背景与边框（Task 7）。

断言 _migrated_btn_qss() 纯函数输出含 rss_control_bg 背景色值与
border: 1px solid 边框，且 hover/pressed/checked/disabled 态与
styles._btn_style 视觉一致（全部令牌驱动，无 hex/rgba 字面量）。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from core.theme.tokens import theme_palette
from modules.rss_aggregator.page_theme import _migrated_btn_qss
from modules.rss_aggregator.text_utils import rss_style_vars


@pytest.mark.parametrize("dark", [True, False])
def test_migrated_btn_qss_has_background_and_border(dark):
    """迁移按钮 QSS 必须含 rss_control_bg 背景 + 1px 边框（可辨识边界）。"""
    _force_dark(dark)
    try:
        qss = _migrated_btn_qss(rss_style_vars())
        p = theme_palette()
        assert p["rss_control_bg"] in qss, "QSS 应含 rss_control_bg 背景色"
        assert p["rss_control_border"] in qss, "QSS 应含 rss_control_border 边框色"
        assert "border: 1px solid" in qss, "QSS 应含 1px 边框"
    finally:
        _restore_dark()


@pytest.mark.parametrize("dark", [True, False])
def test_migrated_btn_qss_states_match_btn_style(dark):
    """hover/pressed/checked/disabled 态与 _btn_style 视觉一致（令牌驱动）。"""
    _force_dark(dark)
    try:
        qss = _migrated_btn_qss(rss_style_vars())
        p = theme_palette()
        assert p["rss_control_bg_hover"] in qss, "hover 应含 rss_control_bg_hover"
        assert p["rss_control_border_hover"] in qss, "hover 应含 rss_control_border_hover"
        assert p["overlay_pressed"] in qss, "pressed 应含 overlay_pressed"
        assert p["rss_accent_bg"] in qss, "checked 应含 rss_accent_bg"
        assert p["rss_text_faint"] in qss, "disabled 应含 rss_text_faint"
    finally:
        _restore_dark()


@pytest.mark.parametrize("dark", [True, False])
def test_rss_btn_primary_style_golden(dark):
    """锁定 _btn_primary_style 现状：rest/hover/pressed/disabled 全令牌，无硬编码色。"""
    from modules.rss_aggregator.styles import _btn_primary_style
    from tests.test_style_tokens import _qss_colors
    _force_dark(dark)
    try:
        qss = _btn_primary_style()
        p = theme_palette()
        assert p["rss_accent"] in qss, "rest 应含 rss_accent"
        assert p["rss_accent_hover"] in qss, "hover 应含 rss_accent_hover"
        assert p["rss_accent_pressed"] in qss, "pressed 应含 rss_accent_pressed"
        assert "border-radius" in qss and "min-height" in qss
        qss_hexes = _qss_colors(qss)
        assert qss_hexes, "QSS 必须有颜色"
        assert all(c in p.values() or c == "#ffffff" for c in qss_hexes), \
            "QSS 中所有 hex 必须来自调色板（禁止硬编码）"
    finally:
        _restore_dark()


@pytest.mark.parametrize("dark", [True, False])
def test_rss_btn_style_checked_state_golden(dark):
    """锁定 _btn_style 现状：次级按钮 checked 态用 rss_accent 高亮。"""
    from modules.rss_aggregator.styles import _btn_style
    from tests.test_style_tokens import _qss_colors
    _force_dark(dark)
    try:
        qss = _btn_style()
        p = theme_palette()
        assert ":checked" in qss, "次级按钮需 checked 态"
        assert p["rss_accent_bg"] in qss, "checked 背景应含 rss_accent_bg"
        assert p["rss_accent"] in qss, "checked 前景应含 rss_accent"
        qss_hexes = _qss_colors(qss)
        assert all(c in p.values() or c == "#ffffff" for c in qss_hexes), \
            "QSS 中所有 hex 必须来自调色板（禁止硬编码）"
    finally:
        _restore_dark()