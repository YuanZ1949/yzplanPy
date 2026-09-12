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


def test_palette_matches_perf_monitor_baseline(_qapp):
    """配色基准 = perf_monitor._theme_colors()。accent 三个值与 perf 基准一致。"""
    from core.theme.tokens import theme_palette
    from modules.perf_monitor.styles import _theme_colors
    for dark in (True, False):
        _force_dark(dark)
        p = theme_palette()
        ref = _theme_colors()
        assert p["accent"] == ref["accent"], "accent 必须以 perf_monitor 为准"
        assert p["text_primary"] == ref["text_primary"]
        assert p["text_secondary"] == ref["text_secondary"]


def test_palette_switches_with_theme_setting(_qapp):
    from core.theme.tokens import theme_palette
    _force_dark(True)
    dark_p = theme_palette()
    _force_dark(False)
    light_p = theme_palette()
    assert dark_p["accent"] != light_p["accent"]
    assert dark_p["bg_card"] != light_p["bg_card"]