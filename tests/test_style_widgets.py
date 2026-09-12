"""控件工厂：高度/颜色/字号全部来自令牌，主题与缩放驱动视觉。"""
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
    # theme_palette() 走 from .base import resolve_dark（模块级绑定），
    # 包级 core.theme.resolve_dark 也一并 patch，与 test_style_tokens 的
    # P-3 双 patch 模式保持一致。
    import core.theme as pkg
    pkg.resolve_dark = lambda mode: dark


def test_make_button_height_from_sizing(_qapp):
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    from ui.widgets import make_button
    ConfigHolder.scale = 1.0
    b1 = make_button("确定", size="md")
    ConfigHolder.scale = 1.6
    b2 = make_button("确定", size="md")
    ConfigHolder.scale = 1.0
    assert b1.height() == sizing()["btn_height_md"]
    assert b2.height() > b1.height(), "1.6x 缩放后按钮高度必须变大（根治截断）"


def test_make_button_primary_uses_accents(_qapp):
    from core.theme.tokens import theme_palette
    from tests.test_style_tokens import _qss_colors
    from ui.widgets import make_button
    _force_dark(True)
    p = theme_palette()
    b = make_button("主操作", kind="primary")
    assert p["accent"] in b.styleSheet(), "主色按钮 QSS 必须引用当前 accent"
    qss_hexes = _qss_colors(b.styleSheet())
    assert all(c in p.values() or c == "#ffffff" for c in qss_hexes), \
        "QSS 中所有 hex 必须来自调色板（禁止硬编码）"


def test_make_line_edit_fixed_height(_qapp):
    from core.theme.tokens import sizing
    from ui.widgets import make_line_edit
    e = make_line_edit("搜索…")
    assert e.height() == sizing()["input_height"]
    assert p_style_uses_tokens(e.styleSheet())


def test_make_status_chip_torrent(_qapp):
    from core.theme.tokens import theme_palette
    from ui.widgets import make_status_chip
    _force_dark(True)
    p = theme_palette()
    chip = make_status_chip("磁链", kind="torrent")
    assert p["chip_torrent_bg"] in chip.styleSheet()
    assert p["chip_torrent_fg"] in chip.styleSheet()


def test_make_label_roles_differ(_qapp):
    from ui.widgets import make_label
    title = make_label("标题", role="title")
    caption = make_label("说明", role="caption")
    assert title.styleSheet() != caption.styleSheet()
    assert "700" in title.styleSheet()


def test_factories_qss_have_no_bare_px_literals(_qapp):
    """工厂 QSS 模板源码不得含裸 px 数字（尺寸必须来自 sizing() 令牌）。

    渲染后的 QSS 必然含令牌注入的 px 值（如 padding: 6px 10px），故护栏校验
    源码模板：任何 padding/width/border-radius 后紧跟数字 px 即违规。
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "ui" / "widgets.py"
    text = src.read_text(encoding="utf-8")
    assert not re.search(r"(?:padding|width|border-radius):\s*\d+px", text), \
        "工厂 QSS 模板含裸 px 字面量，必须改用 sizing() 令牌"


def p_style_uses_tokens(qss):
    """QSS 中不得出现裸 hex 字面量（工厂代码本身已用 f-string 注入令牌）。

    令牌值本身可能是 hex（如暗色 text_primary=#e6e6e6），故不能只查"有无 hex"，
    而要校验 QSS 中每个 hex 都来自当前调色板（令牌注入），而非工厂硬编码。
    """
    import re
    from core.theme.tokens import theme_palette
    palette_hexes = {
        v for v in theme_palette().values()
        if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)
    }
    qss_hexes = set(re.findall(r"#[0-9a-fA-F]{6}", qss))
    return qss_hexes <= palette_hexes