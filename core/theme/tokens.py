"""GUI 设计令牌：全局唯一调色板与尺寸/字号令牌。

颜色以 perf_monitor._theme_colors() 为基准（spec 决策 A）；perf_monitor 缺失
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
        # 面板
        "bg_app": "rgba(245,245,245,0.92)",
        "bg_card": "rgba(0,0,0,0.03)",
        "bg_control": "rgba(0,0,0,0.03)",  # perf_monitor ctrl_bg 亮色基准
        "bg_hover": "rgba(0,0,0,0.05)",
        "bg_selected": "rgba(0,120,215,0.12)",
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
    }