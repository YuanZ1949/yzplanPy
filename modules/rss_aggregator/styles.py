"""RSS 样式：按钮/侧栏 QSS 生成。"""

from .text_utils import rss_style_vars

def _btn_style(min_width=80, padding="6px 16px", radius=8, font_size=13):
    """主题感知的次级按钮样式：半透明面板 + 细边框，支持 hover/checked 态。"""
    c = rss_style_vars()
    return (
        "QPushButton {{ padding: {padding}; border: 1px solid {rss_control_border}; border-radius: {radius}px; "
        "background: {rss_control_bg}; color: {rss_text}; font-size: {font_size}px; "
        "min-width: {min_width}px; min-height: {rss_btn_min_height}px; }}"
        "QPushButton:hover {{ background: {rss_control_bg_hover}; border-color: {rss_control_border_hover}; }}"
        "QPushButton:pressed {{ background: {overlay_pressed}; }}"
        "QPushButton:checked {{ background: {rss_accent_bg}; border-color: {rss_accent}; color: {rss_accent}; }}"
        "QPushButton:disabled {{ color: {rss_text_faint}; background: transparent; border-color: {rss_border}; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _btn_primary_style(min_width=80, padding="6px 16px", radius=8, font_size=13):
    """主题感知的主强调按钮样式：实心强调色，hover/pressed 加深。"""
    c = rss_style_vars()
    return (
        "QPushButton {{ padding: {padding}; border: none; border-radius: {radius}px; "
        "background: {rss_accent}; color: {white}; font-size: {font_size}px; font-weight: bold; "
        "min-width: {min_width}px; min-height: {rss_btn_min_height}px; }}"
        "QPushButton:hover {{ background: {rss_accent_hover}; }}"
        "QPushButton:pressed {{ background: {rss_accent_pressed}; }}"
        "QPushButton:disabled {{ background: {rss_text_faint}; color: {rss_btn_disabled_fg}; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _sidebar_qss():
    """主题感知的侧边栏列表样式：圆角条目 + hover/选中高亮。"""
    c = rss_style_vars()
    return (
        "QListWidget {{ background: {rss_panel}; border-right: 1px solid {rss_border}; "
        "font-size: {rss_font_md}px; border-top: none; border-left: none; border-bottom: none; }}"
        "QListWidget::item {{ margin: {rss_row_margin_0}; padding: 0; border-radius: {rss_radius_sm}px; }}"
        "QListWidget::item:hover {{ background: {rss_row_hover}; }}"
        "QListWidget::item:selected {{ background: {rss_row_selected}; color: {rss_title_unread}; }}"
        "QListWidget::item:selected:hover {{ background: {rss_row_selected}; }}"
        "QPushButton {{ font-size: {rss_font_md}px; padding: {rss_btn_padding}; }}"
    ).format(**c)


def _rss_card_style(radius=9):
    """组件样式：卡片/汇总面板（_MetricCard 对称）——圆角半透明面板 + 细边框。"""
    c = rss_style_vars()
    return (
        "QFrame#rss_card {{ background: {rss_card_bg}; border: 1px solid {rss_card_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_ctrl_style(radius=8):
    """组件样式：控件容器（_ctrl_frame_style 对称）——输入/下拉等控件的宿主面板。"""
    c = rss_style_vars()
    return (
        "QFrame#rss_ctrl {{ background: {rss_ctrl_bg}; border: 1px solid {rss_ctrl_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_head_style(radius=8):
    """组件样式：分组框/浮动标题（_group_box_style 对称）——浮动标题 + 柔底面板。"""
    c = rss_style_vars()
    return (
        "QGroupBox {{ border: 1px solid {rss_group_border}; border-radius: {radius}px; "
        "background: {rss_group_bg}; margin-top: {rss_group_margin_top}px; padding: {rss_group_padding}; }}"
        "QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; "
        "left: 12px; top: 3px; padding: 0 6px; color: {rss_text_primary}; }}"
    ).format(**c, radius=radius)


def _rss_btn_group_style(radius=8, spacing_hint=None):
    """组件样式：按钮组容器——内聚的圆角分组，内部控件透明承底。

    spacing_hint 仅作文档提示（布局间距由调用方 QHBoxLayout/QVBoxLayout 设置）。
    """
    c = rss_style_vars()
    return (
        "QFrame#rss_btn_group {{ background: {rss_btn_group_bg}; border: 1px solid {rss_btn_group_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_menu_style(radius=8):
    """组件样式：下拉菜单——柔和悬浮/选中态（D9 下拉菜单项美化）。"""
    c = rss_style_vars()
    return (
        "QMenu {{ background: {rss_menu_bg}; border: 1px solid {rss_menu_border}; "
        "border-radius: {radius}px; padding: {rss_menu_padding}; }}"
        "QMenu::item {{ padding: {rss_menu_item_padding}; border-radius: {rss_radius_sm}px; "
        "background: transparent; color: {rss_text}; }}"
        "QMenu::item:selected {{ background: {rss_menu_item_selected}; color: {rss_text_primary}; }}"
        "QMenu::item:disabled {{ color: {rss_text_faint}; }}"
        "QMenu::separator {{ height: {rss_sep_height}px; background: {rss_divider}; "
        "margin: {rss_menu_sep_margin}; }}"
    ).format(**c, radius=radius)