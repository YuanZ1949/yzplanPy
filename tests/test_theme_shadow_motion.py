"""第3层视觉令牌：阴影/动效/圆角对齐/窗口底色。"""
from conftest import _force_dark, _restore_dark
from core.theme.tokens import sizing, theme_palette, motion_durations


def test_motion_durations_fluent2_octave():
    d = motion_durations()
    assert d == {"xs": 50, "sm": 100, "md": 150, "lg": 200,
                 "xl": 250, "2xl": 300, "3xl": 400, "4xl": 500}


def test_shadow_tokens_exist():
    sz = sizing()
    assert "shadow_blur" in sz and "shadow_offset" in sz and "radius_xl" in sz


def test_card_shadow_color_present_both_themes():
    try:
        _force_dark(True)
        light = theme_palette(False)
        dark = theme_palette(True)
        assert "card_shadow_color" in light and "card_shadow_color" in dark
        assert light["card_shadow_color"] != dark["card_shadow_color"]
    finally:
        _restore_dark()


def test_window_bg_aligned_fluent():
    p = theme_palette(False)
    assert "240,244,249" in p["bg_app"]      # 亮色 Fluent-M3U8
    p2 = theme_palette(True)
    assert "32,32,32" in p2["bg_app"]        # 暗色 Fluent-M3U8