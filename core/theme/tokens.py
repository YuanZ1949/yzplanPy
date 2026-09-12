"""GUI 设计令牌：全局唯一调色板与尺寸/字号令牌。

颜色以 perf_monitor.perf_palette() 为基准（spec 决策 A）；perf_monitor 缺失
而全局 QSS 已使用的语义色从 qss_dark/qss_light 提取合并。所有模块禁止私有
调色板，一律 from core.theme.tokens import theme_palette。
"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def theme_palette():
    """按当前主题返回完整色板。函数式（非常量）以支持运行时明暗热切换。"""
    from .base import resolve_dark
    dark = resolve_dark("auto")
    if dark:
        return {
            "_theme": True,
            "dark": True,
            # 品牌色（perf_monitor 基准）
            "accent": "#3aa6ff",
            "accent_hover": "#5cb8ff",
            "accent_pressed": "#2a8ad0",
            # 语义色（从 qss_dark 选中色系扩展）
            "success": "#4fd97a",
            "warning": "#ffab40",
            "danger": "#ff6b8a",
            "danger_hover": "#ff8ba4",
            "danger_pressed": "#d84f6e",
            "info": "#5b8cff",
            # 日志级别色（明暗同值，保留原值零视觉变化）
            "log_info": "#1a73e8",
            "log_warning": "#f9a825",
            "log_error": "#c5221f",
            "log_critical": "#7b1fa2",
            "log_source": "#1967d2",
            # 面板
            "bg_app": "rgba(30,30,30,0.92)",
            "bg_card": "rgba(255,255,255,0.06)",
            "bg_control": "rgba(255,255,255,0.05)",
            "bg_hover": "rgba(255,255,255,0.06)",
            "bg_selected": "rgba(0,120,215,0.25)",
            # 边框（值取 perf_monitor card_border/ctrl_border 基准 0.10）
            "border": "rgba(255,255,255,0.10)",
            "border_strong": "rgba(255,255,255,0.18)",
            "border_focus": "rgba(58,166,255,0.60)",
            # 文字
            "text_primary": "#e6e6e6",
            "text_secondary": "#999999",
            "text_disabled": "rgba(255,255,255,0.35)",
            # 状态胶囊（RSS 用）
            "chip_torrent_bg": "rgba(255,107,142,0.16)",
            "chip_torrent_fg": "#ff9ab0",
            "chip_article_bg": "rgba(37,205,150,0.16)",
            "chip_article_fg": "#7fe0c0",
            # 通用覆盖态
            "overlay_pressed": "rgba(0,0,0,0.10)",
            # perf_monitor 图表扩展（T4 并入全局色板，保原值零视觉变化）
            "perf_accent_pid": "#5b8cff", "perf_accent_cpu": "#25c9a0",
            "perf_accent_mem": "#a06bff", "perf_accent_thr": "#ffab40",
            "perf_accent_hdl": "#ff6b8a", "perf_accent_uptime": "#4fd97a",
            "perf_group_border": "rgba(255,255,255,0.12)",
            "perf_group_bg": "rgba(255,255,255,0.04)",
            "perf_grid_color": "rgba(255,255,255,0.06)",
            "perf_bar_colors": [(0, 180, 80), (60, 170, 50), (180, 160, 0),
                                (220, 120, 0), (220, 60, 40)],
            # 条形文字对比色（明暗同值）
            "perf_bar_text_dark": "#0f0f0f", "perf_bar_text_light": "#ffffff",
            # todo_notes 专属（保原值零视觉变化）
            "todo_category": "#8e44ad",
            "todo_priority_urgent": "#c0392b",
            "todo_table_sel_bg": "rgba(128,128,128,0.12)",
            # 日历控件（QCalendarWidget 弹窗为独立顶层窗口，透明令牌会与桌面
            # 背景混合，故保原值实色）
            "calendar_bg": "#1e1e1e",
            "calendar_nav_bg": "#232323",
            "calendar_ctrl_bg": "#2b2b2b",
            "calendar_sel_bg": "#3a6ea5",
            "calendar_sel_fg": "#ffffff",
            # sys_info 编辑区背景（保原值）
            "sysinfo_edit_bg": "rgba(255,255,255,0.05)",
            # webview_control / translator 状态色（明暗同值，保原值零视觉变化）
            "webview_pending": "#e67e22", "webview_allowed": "#27ae60",
            "webview_blocked": "#e74c3c",
            "status_warning": "#e8710a", "status_error": "#d93025", "status_info": "#1a73e8",
            # RSS 关键词监控高亮色（保原值零视觉变化）
            "rss_keyword_color": "#ff6b6b",
            # RSS 聚合模块专属色板（rss_aggregator 迁移，保原值零视觉变化）
            "rss_panel": "rgba(24,24,27,0.74)",
            "rss_panel_soft": "rgba(24,24,27,0.64)",
            "rss_panel_card": "rgba(255,255,255,0.05)",
            "rss_border": "rgba(255,255,255,0.08)",
            "rss_border_strong": "rgba(255,255,255,0.16)",
            "rss_accent": "#4aa3ff",
            "rss_accent_hover": "#6eb6ff",
            "rss_accent_pressed": "#2f8ae6",
            "rss_accent_bg": "rgba(74,163,255,0.16)",
            "rss_text": "#e8e8e8",
            "rss_text_secondary": "#9a9a9a",
            "rss_text_faint": "#76767a",
            "rss_title_unread": "#ffffff",
            "rss_title_read": "#8a8a8a",
            "rss_control_bg": "rgba(255,255,255,0.09)",
            "rss_control_bg_hover": "rgba(255,255,255,0.12)",
            "rss_control_border": "rgba(255,255,255,0.10)",
            "rss_control_border_hover": "rgba(255,255,255,0.22)",
            "rss_pill_tag_bg": "rgba(74,163,255,0.18)",
            "rss_pill_tag_fg": "#8fc2ff",
            "rss_pill_torrent_bg": "rgba(255,107,107,0.16)",
            "rss_pill_torrent_fg": "#ff9a9a",
            "rss_pill_article_bg": "rgba(37,205,150,0.16)",
            "rss_pill_article_fg": "#7fe0c0",
            "rss_badge_bg": "rgba(74,163,255,0.22)",
            "rss_badge_fg": "#9cc8ff",
            "rss_fav_color": "#ffc107",
            "rss_row_hover": "rgba(255,255,255,0.05)",
            "rss_row_selected": "rgba(0,120,215,0.30)",
            "rss_header_bg": "rgba(255,255,255,0.05)",
            "rss_header_border": "rgba(255,255,255,0.10)",
            "rss_card_border": "rgba(255,255,255,0.10)",
            "rss_divider": "rgba(255,255,255,0.06)",
            "rss_dot_unread": "#4aa3ff",
            "rss_dot_read": "rgba(255,255,255,0.16)",
            "rss_group_border": "rgba(255,255,255,0.12)",
            "rss_group_bg": "rgba(255,255,255,0.04)",
            "rss_card_bg": "rgba(255,255,255,0.05)",
            "rss_ctrl_bg": "rgba(255,255,255,0.05)",
            "rss_ctrl_border": "rgba(255,255,255,0.10)",
            "rss_grid_color": "rgba(255,255,255,0.06)",
            "rss_sel_bg": "rgba(0,120,215,0.25)",
            "rss_text_primary": "#e8e8e8",
            "rss_btn_group_bg": "rgba(255,255,255,0.04)",
            "rss_btn_group_border": "rgba(255,255,255,0.08)",
            "rss_menu_bg": "rgba(42,42,44,0.94)",
            "rss_menu_border": "rgba(255,255,255,0.10)",
            "rss_menu_item_hover": "rgba(255,255,255,0.08)",
            "rss_menu_item_selected": "rgba(74,163,255,0.25)",
            "rss_badge": {
                "all": {"bg": "rgba(74,163,255,0.38)", "fg": "#c4deff"},
                "unread": {"bg": "rgba(37,205,150,0.35)", "fg": "#a8f0d8"},
                "fav": {"bg": "rgba(255,193,7,0.32)", "fg": "#ffe88a"},
                "torrent": {"bg": "rgba(255,107,107,0.34)", "fg": "#ffb8b8"},
                "agg": {"bg": "rgba(160,107,255,0.36)", "fg": "#d8c8ff"},
                "feed": {"bg": "rgba(255,255,255,0.28)", "fg": "#e8e8ec"},
            },
            # RSS 状态胶囊（磁链/文章 chip，预览区与状态胶囊共用）
            "rss_chip_torrent_bg": "rgba(255,107,142,0.16)",
            "rss_chip_torrent_fg": "#ff9ab0",
            "rss_chip_article_bg": "rgba(37,205,150,0.16)",
            "rss_chip_article_fg": "#7fe0c0",
            # RSS 内置阅读视图 HTML 配色（_summary_html）
            "rss_summary_bg": "#1e1f22",
            "rss_summary_fg": "#e8e8e8",
            "rss_summary_sec": "#9a9a9a",
            "rss_summary_faint": "#76767a",
            "rss_summary_pre_bg": "rgba(255,255,255,0.06)",
            "rss_summary_quote_line": "rgba(255,255,255,0.18)",
            "rss_summary_border": "rgba(255,255,255,0.16)",
            "rss_summary_accent": "#5aa6ff",
            # RSS 页面渐变底色（page.py paintEvent）
            "rss_page_bg": "#1b1c1f",
            # RSS 缩略图占位底色 / 禁用按钮文字 / 分类颜色默认值
            "rss_thumb_bg": "#f0f0f0",
            "rss_btn_disabled_fg": "#aaaaaa",
            "rss_category_color": "#1a73e8",
            # 通用纯白（RSS 主按钮文字等）
            "white": "#ffffff",
            # 主页卡片背景（core.constants 默认配置引用，保原值零视觉变化）
            "home_bg": "#1e1e2e",
            # 全局强调色（qfluentwidgets setThemeColor 与 palette Highlight 同源）
            "accent_highlight": "#0078d7",
        }
    return {
        "_theme": True,
        "dark": False,
        # 品牌色（perf_monitor 基准）
        "accent": "#1178e0",
        "accent_hover": "#2a8bf0",
        "accent_pressed": "#0d60b0",
        # 语义色
        "success": "#2f9e5a",
        "warning": "#e08a1e",
        "danger": "#e4506f",
        "danger_hover": "#e86984",
        "danger_pressed": "#c03a58",
        "info": "#4a77f5",
        # 日志级别色（明暗同值，保留原值零视觉变化）
        "log_info": "#1a73e8",
        "log_warning": "#f9a825",
        "log_error": "#c5221f",
        "log_critical": "#7b1fa2",
        "log_source": "#1967d2",
        # 面板
        "bg_app": "rgba(245,245,245,0.92)",
        "bg_card": "rgba(0,0,0,0.03)",
        "bg_control": "rgba(0,0,0,0.03)",  # perf_monitor ctrl_bg 亮色基准
        "bg_hover": "rgba(0,0,0,0.05)",
        "bg_selected": "rgba(0,120,215,0.18)",
        # 边框
        "border": "rgba(0,0,0,0.08)",
        "border_strong": "rgba(0,0,0,0.15)",
        "border_focus": "rgba(17,120,224,0.50)",
        # 文字
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "text_disabled": "rgba(0,0,0,0.30)",
        # 状态胶囊（RSS 用）
        "chip_torrent_bg": "#fce8e6",
        "chip_torrent_fg": "#c5221f",
        "chip_article_bg": "#e6f4ea",
        "chip_article_fg": "#137333",
        # 通用覆盖态
        "overlay_pressed": "rgba(0,0,0,0.10)",
        # perf_monitor 图表扩展（T4 并入全局色板，保原值零视觉变化）
        "perf_accent_pid": "#4a77f5", "perf_accent_cpu": "#12a582",
        "perf_accent_mem": "#7c3aed", "perf_accent_thr": "#e08a1e",
        "perf_accent_hdl": "#e4506f", "perf_accent_uptime": "#2f9e5a",
        "perf_group_border": "rgba(0,0,0,0.10)",
        "perf_group_bg": "rgba(0,0,0,0.02)",
        "perf_grid_color": "rgba(0,0,0,0.06)",
        "perf_bar_colors": [(34, 160, 70), (70, 150, 40), (200, 160, 0),
                            (210, 110, 0), (210, 50, 30)],
        # 条形文字对比色（明暗同值）
        "perf_bar_text_dark": "#0f0f0f", "perf_bar_text_light": "#ffffff",
        # todo_notes 专属（保原值零视觉变化）
        "todo_category": "#8e44ad",
        "todo_priority_urgent": "#c0392b",
        "todo_table_sel_bg": "rgba(128,128,128,0.12)",
        # 日历控件（亮色分支原值：默认白底 + 亮选中）
        "calendar_bg": "#ffffff",
        "calendar_nav_bg": "#ffffff",
        "calendar_ctrl_bg": "#ffffff",
        "calendar_sel_bg": "#d9e7f7",
        "calendar_sel_fg": "#1a1a1a",
        # sys_info 编辑区背景（保原值）
        "sysinfo_edit_bg": "rgba(255,255,255,0.96)",
        # webview_control / translator 状态色（明暗同值，保原值零视觉变化）
        "webview_pending": "#e67e22", "webview_allowed": "#27ae60",
        "webview_blocked": "#e74c3c",
        "status_warning": "#e8710a", "status_error": "#d93025", "status_info": "#1a73e8",
        # RSS 关键词监控高亮色（保原值零视觉变化）
        "rss_keyword_color": "#ff6b6b",
        # RSS 聚合模块专属色板（rss_aggregator 迁移，保原值零视觉变化）
        "rss_panel": "rgba(247,247,250,0.90)",
        "rss_panel_soft": "rgba(248,248,251,0.86)",
        "rss_panel_card": "rgba(255,255,255,0.96)",
        "rss_border": "rgba(0,0,0,0.10)",
        "rss_border_strong": "rgba(0,0,0,0.16)",
        "rss_accent": "#1178e0",
        "rss_accent_hover": "#0d5cb8",
        "rss_accent_pressed": "#0a4a96",
        "rss_accent_bg": "rgba(17,120,224,0.10)",
        "rss_text": "#1f1f1f",
        "rss_text_secondary": "#666666",
        "rss_text_faint": "#999999",
        "rss_title_unread": "#111111",
        "rss_title_read": "#9a9a9a",
        "rss_control_bg": "rgba(255,255,255,0.98)",
        "rss_control_bg_hover": "rgba(0,0,0,0.06)",
        "rss_control_border": "rgba(0,0,0,0.10)",
        "rss_control_border_hover": "rgba(0,0,0,0.16)",
        "rss_pill_tag_bg": "#e8f0fe",
        "rss_pill_tag_fg": "#1967d2",
        "rss_pill_torrent_bg": "#fce8e6",
        "rss_pill_torrent_fg": "#c5221f",
        "rss_pill_article_bg": "#e6f4ea",
        "rss_pill_article_fg": "#137333",
        "rss_badge_bg": "#e8f0fe",
        "rss_badge_fg": "#1967d2",
        "rss_fav_color": "#ffb300",
        "rss_row_hover": "rgba(0,120,215,0.06)",
        "rss_row_selected": "rgba(0,120,215,0.16)",
        "rss_header_bg": "rgba(255,255,255,0.72)",
        "rss_header_border": "rgba(0,0,0,0.10)",
        "rss_card_border": "rgba(0,0,0,0.10)",
        "rss_divider": "rgba(0,0,0,0.06)",
        "rss_dot_unread": "#1178e0",
        "rss_dot_read": "rgba(0,0,0,0.16)",
        "rss_group_border": "rgba(0,0,0,0.10)",
        "rss_group_bg": "rgba(0,0,0,0.02)",
        "rss_card_bg": "rgba(255,255,255,0.96)",
        "rss_ctrl_bg": "rgba(255,255,255,0.98)",
        "rss_ctrl_border": "rgba(0,0,0,0.10)",
        "rss_grid_color": "rgba(0,0,0,0.06)",
        "rss_sel_bg": "rgba(0,120,215,0.16)",
        "rss_text_primary": "#1f1f1f",
        "rss_btn_group_bg": "rgba(0,0,0,0.03)",
        "rss_btn_group_border": "rgba(0,0,0,0.08)",
        "rss_menu_bg": "rgba(252,252,252,0.98)",
        "rss_menu_border": "rgba(0,0,0,0.10)",
        "rss_menu_item_hover": "rgba(0,0,0,0.05)",
        "rss_menu_item_selected": "rgba(17,120,224,0.16)",
        "rss_badge": {
            "all": {"bg": "#e8f0fe", "fg": "#1967d2"},
            "unread": {"bg": "#e6f4ea", "fg": "#137333"},
            "fav": {"bg": "#fff6dd", "fg": "#b26a00"},
            "torrent": {"bg": "#fce8e6", "fg": "#c5221f"},
            "agg": {"bg": "#f0eaff", "fg": "#6a3fd8"},
            "feed": {"bg": "rgba(0,0,0,0.06)", "fg": "#5f6368"},
        },
        # RSS 状态胶囊（磁链/文章 chip，预览区与状态胶囊共用）
        "rss_chip_torrent_bg": "#fce8e6",
        "rss_chip_torrent_fg": "#c5221f",
        "rss_chip_article_bg": "#e6f4ea",
        "rss_chip_article_fg": "#137333",
        # RSS 内置阅读视图 HTML 配色（_summary_html）
        "rss_summary_bg": "#ffffff",
        "rss_summary_fg": "#1f1f1f",
        "rss_summary_sec": "#666666",
        "rss_summary_faint": "#999999",
        "rss_summary_pre_bg": "#f6f8fa",
        "rss_summary_quote_line": "#e0e0e0",
        "rss_summary_border": "#dddddd",
        "rss_summary_accent": "#1967d2",
        # RSS 页面渐变底色（page.py paintEvent）
        "rss_page_bg": "#e9ebf0",
        # RSS 缩略图占位底色 / 禁用按钮文字 / 分类颜色默认值
        "rss_thumb_bg": "#f0f0f0",
        "rss_btn_disabled_fg": "#aaaaaa",
        "rss_category_color": "#1a73e8",
        # 通用纯白（RSS 主按钮文字等）
        "white": "#ffffff",
        # 主页卡片背景（core.constants 默认配置引用，保原值零视觉变化）
        "home_bg": "#1e1e2e",
        # 全局强调色（qfluentwidgets setThemeColor 与 palette Highlight 同源）
        "accent_highlight": "#0078d7",
    }


def _s(px):
    """将 px 基线值按当前字体缩放比例实时缩放（scale 0.7~1.6）。"""
    from .font import current_font_scale
    return round(px * current_font_scale())


def sizing():
    """尺寸/字号令牌。每次调用实时计算——运行时字体缩放（设置页切换）立即生效。

    控件高度 = 基线高度 × scale：字号放大时高度同步增长，杜绝固定像素截断。
    """
    return {
        # 按钮
        "btn_height_sm": _s(26),
        "btn_height_md": _s(32),
        "btn_height_lg": _s(38),
        "btn_padding_sm": f"{_s(4)}px {_s(10)}px",
        "btn_padding_md": f"{_s(6)}px {_s(14)}px",
        "btn_padding_lg": f"{_s(8)}px {_s(18)}px",
        # 输入框 / 下拉框
        "input_height": _s(30),
        "input_h_padding": _s(10),
        "combo_height": _s(30),
        "combo_padding": f"{_s(4)}px {_s(10)}px",
        "combo_drop_width": _s(20),
        # 圆角
        "radius_sm": _s(4),
        "radius_md": _s(6),
        "radius_lg": _s(8),
        # 状态胶囊
        "chip_border_extra": _s(10),
        "chip_padding_h": _s(10),
        # 标题栏 / 工具栏 / 表格
        "toolbar_height": _s(48),
        "title_bar_height": _s(28),
        "log_table_min_height": _s(200),
        # perf_monitor 图表/页面/卡片
        "perf_chart_min_height": _s(140),
        "perf_chart_min_width": _s(140),
        "perf_tabs_min_height": _s(440),
        "perf_card_radius": _s(9),
        "perf_group_margin_top": _s(14),
        "perf_group_padding": f"{_s(8)}px {_s(6)}px {_s(6)}px {_s(6)}px",
        "perf_title_padding": f"0 {_s(6)}px",
        "perf_item_padding": f"{_s(2)}px {_s(4)}px",
        "perf_tab_padding": f"{_s(8)}px {_s(16)}px",
        # 字号
        "font_size_xs": _s(9),
        "font_size_sm": _s(11),
        "font_size_md": _s(13),
        "font_size_lg": _s(16),
        "font_size_xl": _s(20),
        # todo_notes 表格 / sys_info 编辑区
        "todo_table_item_padding": f"{_s(3)}px",
        "sysinfo_edit_min_height": _s(80),
        "sysinfo_edit_padding": f"{_s(8)}px",
        # 页面选择器模式提示标签（dialog_core mode_label）
        "hint_padding": f"{_s(4)}px {_s(6)}px",
        # RSS 聚合模块（rss_aggregator 迁移，随字体缩放）
        "rss_font_xs": _s(10),
        "rss_font_sm": _s(11),
        "rss_font_md": _s(12),
        "rss_font_lg": _s(14),
        "rss_radius_xs": _s(2),
        "rss_radius_sm": _s(6),
        "rss_radius_md": _s(8),
        "rss_radius_lg": _s(9),
        "rss_radius_xl": _s(10),
        "rss_radius_2xl": _s(12),
        "rss_radius_3xl": _s(14),
        "rss_btn_min_height": _s(20),
        "rss_summary_status_height": _s(22),
        "rss_sep_height": _s(1),
        "rss_feed_list_min_height": _s(80),
        "rss_sidebar_btn_height": _s(30),
        "rss_group_margin_top": _s(16),
        "rss_pill_padding": f"{_s(3)}px {_s(10)}px",
        "rss_item_padding": f"{_s(3)}px {_s(5)}px",
        "rss_card_padding": f"{_s(12)}px",
        "rss_empty_padding": f"{_s(20)}px",
        "rss_thumb_padding": f"{_s(1)}px {_s(8)}px",
        "rss_badge_padding": f"{_s(2)}px {_s(9)}px",
        "rss_menu_item_padding": f"{_s(5)}px {_s(22)}px {_s(5)}px {_s(10)}px",
        "rss_menu_sep_margin": f"{_s(4)}px {_s(8)}px",
        "rss_group_padding": f"{_s(10)}px {_s(8)}px {_s(8)}px {_s(8)}px",
        "rss_btn_padding": f"{_s(4)}px {_s(10)}px",
        "rss_hint_padding": f"{_s(8)}px {_s(4)}px",
        "rss_meta_padding": f"{_s(2)}px {_s(10)}px 0 {_s(10)}px",
        "rss_row_margin": f"{_s(1)}px {_s(3)}px",
        "rss_row_margin_0": f"0 {_s(3)}px",
        "rss_thumb_radius": _s(4),
        "rss_pre_padding": f"{_s(10)}px",
        "rss_table_padding": f"{_s(6)}px {_s(10)}px",
        "rss_img_radius": _s(4),
        "rss_body_padding": f"{_s(20)}px",
        "rss_compact_btn_height": _s(28),
        "rss_title_padding": f"{_s(2)}px",
        "rss_menu_padding": f"{_s(4)}px",
    }