"""运行时护栏：
1) 主题切换后，工厂控件 QSS 必须全部来自新主题调色板（无旧主题残留）。
2) 字体缩放 1.6x 下，按钮文字完整可见（不截断）。
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


def _force_dark(dark):
    import core.theme.base as base
    base.resolve_dark = lambda mode: dark
    # 与 test_style_tokens.py 相同的 P-3 双 patch：theme_palette 走
    # from .base import resolve_dark（模块级绑定），但其他代码可能走
    # from core.theme import resolve_dark（包级绑定），一并 patch 保证一致。
    import core.theme as pkg
    pkg.resolve_dark = lambda mode: dark


def _qss_colors(qss):
    """提取 QSS 中出现的所有 #hex 与 rgba(...)。"""
    hexes = re.findall(r"#[0-9a-fA-F]{6}\b", qss)
    return set(hexes)


def _palette_colors(p):
    """调色板中全部 #hex 值集合。"""
    return {v for v in p.values() if isinstance(v, str) and v.startswith("#")}


def test_theme_switch_no_stale_colors_on_factory_widgets(_qapp):
    """切到暗色后，工厂控件 QSS 中不得残留亮色专有色。"""
    from core.theme.tokens import theme_palette
    from ui.widgets import make_button, make_label, make_status_chip
    _force_dark(False)
    light_only = _palette_colors(theme_palette())
    _force_dark(True)
    dark_only = _palette_colors(theme_palette())
    stale = light_only - dark_only  # 亮色专有、暗色没有的颜色
    assert stale, "测试前提：明暗调色板必须有差异色"

    # 用暗色主题创建全套工厂控件，遍历其 QSS 断言无亮色残留
    _force_dark(True)
    widgets = [
        make_button("确定", kind="primary"),
        make_button("幽灵", kind="ghost"),
        make_label("标题", role="title"),
        make_status_chip("磁链", kind="torrent"),
    ]
    for w in widgets:
        found = _qss_colors(w.styleSheet()) & stale
        assert not found, f"{type(w).__name__} 残留亮色: {found}"


def test_font_scale_16_button_text_fits(_qapp):
    """1.6x 缩放下按钮文字+内边距必须装得下（截断护栏）。"""
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    from ui.widgets import make_button
    ConfigHolder.scale = 1.6
    try:
        btn = make_button("保存设置", kind="default")
        btn.show()
        fm = QtGui.QFontMetrics(btn.font())
        text_w = fm.horizontalAdvance(btn.text())
        pad_w = int(sizing()["btn_padding_md"].split()[1].rstrip("px")) * 2
        assert btn.width() >= text_w + pad_w + 2, \
            f"文字 {text_w}px + 内边距 {pad_w}px 超出按钮宽 {btn.width()}px"
        assert btn.height() >= fm.height() + 4, \
            f"文字高 {fm.height()}px 超出按钮高 {btn.height()}px"
    finally:
        ConfigHolder.scale = 1.0
        btn.close()