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
    }