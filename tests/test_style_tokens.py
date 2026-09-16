"""颜色令牌 theme_palette：完整性 + perf_monitor 基准色值。"""
import pytest

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

# 调色板 key 全集：测试强制每个 key 在明暗两套中都存在（防缺 key 导致工厂 KeyError）
_PALETTE_KEYS = {
    "_theme", "dark", "accent", "accent_hover", "accent_pressed",
    "success", "warning", "danger", "danger_hover", "danger_pressed", "info",
    "log_info", "log_warning", "log_error", "log_critical", "log_source",
    "bg_app", "bg_card", "bg_control", "bg_hover", "bg_selected",
    "border", "border_strong", "border_focus",
    "text_primary", "text_secondary", "text_disabled",
    "chip_torrent_bg", "chip_torrent_fg", "chip_article_bg", "chip_article_fg",
    "overlay_pressed",
    # perf_monitor 图表扩展（T4 并入全局色板）
    "perf_accent_pid", "perf_accent_cpu", "perf_accent_mem", "perf_accent_thr",
    "perf_accent_hdl", "perf_accent_uptime", "perf_group_border", "perf_group_bg",
    "perf_grid_color", "perf_bar_colors", "perf_bar_text_dark", "perf_bar_text_light",
    "perf_list_sel_bg", "perf_watch_border", "perf_watch_bg",
    # todo_notes / 日历 / sys_info（T5 并入全局色板）
    "todo_category", "todo_priority_urgent", "todo_table_sel_bg",
    "todo_badge_bg", "todo_item_border", "todo_item_hover_bg", "todo_done_bg",
    "calendar_bg", "calendar_nav_bg", "calendar_ctrl_bg",
    "calendar_sel_bg", "calendar_sel_fg",
    "sysinfo_edit_bg",
    # webview_control / translator 状态色（T6 并入全局色板，明暗同值）
    "webview_pending", "webview_allowed", "webview_blocked",
    "status_warning", "status_error", "status_info",
    # rss_aggregator（T8 并入全局色板，保原值零视觉变化）
    "rss_keyword_color",
    "rss_panel", "rss_panel_soft",
    "rss_border", "rss_border_strong",
    "rss_accent", "rss_accent_hover", "rss_accent_pressed", "rss_accent_bg",
    "rss_text", "rss_text_secondary", "rss_text_faint",
    "rss_title_unread", "rss_title_read",
    "rss_control_bg", "rss_control_bg_hover",
    "rss_control_border", "rss_control_border_hover",
    "rss_pill_tag_bg", "rss_pill_tag_fg",
    "rss_pill_torrent_bg", "rss_pill_torrent_fg",
    "rss_pill_article_bg", "rss_pill_article_fg",
    "rss_badge_bg", "rss_badge_fg",
    "rss_fav_color",
    "rss_row_hover", "rss_row_selected",
    "rss_card_border", "rss_divider",
    "rss_dot_unread", "rss_dot_read",
    "rss_group_border", "rss_group_bg",
    "rss_card_bg", "rss_ctrl_bg", "rss_ctrl_border",
    "rss_text_primary",
    "rss_btn_group_bg", "rss_btn_group_border",
    "rss_menu_bg", "rss_menu_border",
    "rss_menu_item_selected",
    "rss_badge",
    "rss_chip_torrent_bg", "rss_chip_torrent_fg",
    "rss_chip_article_bg", "rss_chip_article_fg",
    "rss_summary_bg", "rss_summary_fg", "rss_summary_sec", "rss_summary_faint",
    "rss_summary_pre_bg", "rss_summary_quote_line",
    "rss_summary_border", "rss_summary_accent",
    "rss_page_bg",
    "rss_thumb_bg", "rss_btn_disabled_fg", "rss_category_color",
    # 通用纯白 / 主页卡片 / 表格 / 托盘 / 弹窗 / 字幕 / MCP 命令 / 强调色
    "white", "home_bg",
    "table_gridline", "table_sel_strong_bg", "table_sel_bg",
    "tray_menu_indicator_border", "tray_menu_btn_bg", "tray_menu_btn_border",
    "picker_bg", "picker_border",
    "subtitle_orig_fg",
    "mcp_cmd_bg", "mcp_cmd_border",
    "accent_highlight",
    # 全局 tab（C0：QTabBar/QTabWidget 令牌驱动样式）
    "tab_text", "tab_text_hover", "tab_text_selected", "tab_bg_selected", "tab_indicator",
    # todo 编辑器（C1：选项默认色轮换 + 编辑器边框）
    "todo_option_palette", "todo_editor_bg", "todo_editor_border", "todo_editor_border_hover",
    # wp 时间线（C4：win_maintenance 聚合时间线图表）
    "wp_timeline_bar_bg", "wp_timeline_grid", "wp_timeline_axis", "wp_timeline_track",
    # sysinfo 行（C6：配置信息模块行式布局）
    "sysinfo_label_fg", "sysinfo_row_border", "sysinfo_value_bg",
    # 全局 QSS 兜底（T9 收敛 qss_dark/qss_light，保原值零视觉变化）
    "qss_bg_acrylic", "qss_list_sel_bg", "qss_list_item_hover", "qss_menu_sel_bg",
    "qss_scrollbar_bg", "qss_scrollbar_hover",
    "qss_btn_bg", "qss_btn_border", "qss_btn_text",
    "qss_btn_bg_hover", "qss_btn_border_hover", "qss_btn_bg_pressed",
    "qss_input_bg", "qss_input_border", "qss_input_text",
    "qss_selection_bg", "qss_focus_border", "qss_combo_bg",
    "qss_indicator_border", "qss_indicator_hover_border", "qss_indicator_hover_bg",
    "qss_indicator_checked_bg", "qss_indicator_checked_border",
    "qss_indicator_checked_hover_bg", "qss_indicator_checked_hover_border",
    "qss_indicator_disabled_border", "qss_checkbox_disabled",
    "qss_menu_bg", "qss_menu_border", "qss_dialog_bg",
}


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_palette_has_all_keys_both_themes(_qapp):
    from core.theme.tokens import theme_palette
    try:
        for dark in (True, False):
            _force_dark(dark)
            p = theme_palette()
            missing = _PALETTE_KEYS - set(p.keys())
            assert not missing, f"{'暗' if dark else '亮'}色板缺 key: {missing}"
            assert p["dark"] is dark
            # 自校验：调色板新增 rss_*/qss_* key 必须登记进 _PALETTE_KEYS（防静默漏检）
            uncovered = {k for k in p if k.startswith(("rss_", "qss_"))} - _PALETTE_KEYS
            assert not uncovered, \
                f"调色板新增 rss_*/qss_* key 未登记进 _PALETTE_KEYS: {uncovered}"
    finally:
        _restore_dark()


def _qss_colors(qss):
    """提取 QSS 中所有 #hex 颜色（供其他样式测试复用）。"""
    import re
    return set(re.findall(r"#[0-9a-fA-F]{6}", qss))


def test_perf_palette_is_superset_of_global_palette(_qapp):
    """结构断言：perf 色板必须覆盖全局色板全部 key（防退回独立色板/丢 key）。"""
    from core.theme.tokens import theme_palette
    from modules.perf_monitor.styles import perf_palette
    try:
        for dark in (True, False):
            _force_dark(dark)
            tc = perf_palette()
            gp = theme_palette()
            assert set(tc.keys()) >= set(gp.keys())
            # perf 专属扩展 key 必须存在
            for k in ("perf_accent_pid", "perf_accent_cpu", "perf_accent_mem",
                      "perf_accent_thr", "perf_accent_hdl", "perf_accent_uptime",
                      "perf_group_border", "perf_group_bg", "perf_grid_color",
                      "perf_bar_colors"):
                assert k in tc
    finally:
        _restore_dark()


def test_palette_switches_with_theme_setting(_qapp):
    from core.theme.tokens import theme_palette
    try:
        _force_dark(True)
        dark_p = theme_palette()
        _force_dark(False)
        light_p = theme_palette()
        assert dark_p["accent"] != light_p["accent"]
        assert dark_p["bg_card"] != light_p["bg_card"]
    finally:
        _restore_dark()


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
        # todo_notes / sys_info（T5）
        "todo_table_item_padding", "sysinfo_edit_min_height", "sysinfo_edit_padding",
        # 全局 tab / todo 编辑器 / wp 时间线 / sysinfo 行（C0/C1/C4/C6）
        "tab_padding", "tab_margin", "tab_indicator_height",
        "todo_editor_padding", "todo_editor_border_width",
        "wp_timeline_row_height", "wp_timeline_axis_width", "wp_timeline_bar_radius",
        "sysinfo_row_height", "sysinfo_label_width",
    }
    assert keys <= set(sizing().keys())