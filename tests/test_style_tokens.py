"""颜色令牌 theme_palette：完整性 + perf_monitor 基准色值。"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

# 调色板 key 全集：测试强制每个 key 在明暗两套中都存在（防缺 key 导致工厂 KeyError）
_PALETTE_KEYS = {
    "dark", "accent", "accent_hover", "accent_pressed",
    "success", "warning", "danger", "danger_hover", "danger_pressed", "info",
    "bg_app", "bg_card", "bg_control", "bg_hover", "bg_selected",
    "border", "border_strong", "border_focus",
    "text_primary", "text_secondary", "text_disabled",
    "chip_torrent_bg", "chip_torrent_fg", "chip_article_bg", "chip_article_fg",
    "overlay_pressed",
}


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _force_dark(dark):
    import core.theme.base as base
    base.resolve_dark = lambda mode: dark
    # perf_monitor._theme_colors() 走 from core.theme import resolve_dark
    # （包级绑定），必须一并 patch 才能让基准对比测试生效。
    import core.theme as pkg
    pkg.resolve_dark = lambda mode: dark


def test_palette_has_all_keys_both_themes(_qapp):
    from core.theme.tokens import theme_palette
    for dark in (True, False):
        _force_dark(dark)
        p = theme_palette()
        missing = _PALETTE_KEYS - set(p.keys())
        assert not missing, f"{'暗' if dark else '亮'}色板缺 key: {missing}"
        assert p["dark"] is dark


def _qss_colors(qss):
    """提取 QSS 中所有 #hex 颜色（供其他样式测试复用）。"""
    import re
    return set(re.findall(r"#[0-9a-fA-F]{6}", qss))


def test_perf_palette_is_superset_of_global_palette(_qapp):
    """结构断言：perf 别名必须覆盖全局色板全部 key（防退回独立色板/丢 key）。"""
    from core.theme.tokens import theme_palette
    from modules.perf_monitor.styles import _theme_colors
    for dark in (True, False):
        _force_dark(dark)
        tc = _theme_colors()
        gp = theme_palette()
        assert set(tc.keys()) >= set(gp.keys())
        # perf 专属扩展 key 必须存在
        for k in ("accent_pid", "accent_cpu", "accent_mem", "accent_thr",
                  "accent_hdl", "accent_uptime", "group_border", "group_bg",
                  "grid_color", "bar_colors"):
            assert k in tc


def test_palette_switches_with_theme_setting(_qapp):
    from core.theme.tokens import theme_palette
    _force_dark(True)
    dark_p = theme_palette()
    _force_dark(False)
    light_p = theme_palette()
    assert dark_p["accent"] != light_p["accent"]
    assert dark_p["bg_card"] != light_p["bg_card"]


def test_sizing_scales_with_font_scale(_qapp):
    """字号缩放 1.6x 时，高度/字号/内边距同步放大——这是根治截断的关键。"""
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    ConfigHolder.scale = 1.0
    base = sizing()
    ConfigHolder.scale = 1.6
    scaled = sizing()
    ConfigHolder.scale = 1.0  # 复原，避免污染其他测试
    assert scaled["btn_height_md"] >= int(base["btn_height_md"] * 1.5)
    assert scaled["font_size_md"] > base["font_size_md"]
    # 内边距字符串同步放大
    def parse(p):
        h, w = p.split()
        return int(h.rstrip("px")), int(w.rstrip("px"))
    bh, bw = parse(scaled["btn_padding_md"])
    nh, nw = parse(base["btn_padding_md"])
    assert bh >= nh and bw >= nw


def test_sizing_has_all_keys(_qapp):
    from core.theme.tokens import sizing
    keys = {
        "btn_height_sm", "btn_height_md", "btn_height_lg",
        "btn_padding_sm", "btn_padding_md", "btn_padding_lg",
        "input_height", "combo_height",
        "radius_sm", "radius_md", "radius_lg",
        "font_size_xs", "font_size_sm", "font_size_md", "font_size_lg", "font_size_xl",
    }
    assert keys <= set(sizing().keys())