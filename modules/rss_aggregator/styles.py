"""RSS 样式：按钮/侧栏 QSS 生成。"""

from .text_utils import _rss_colors

def _btn_style(min_width=80, padding="6px 16px", radius=8, font_size=13):
    """主题感知的次级按钮样式：半透明面板 + 细边框，支持 hover/checked 态。"""
    c = _rss_colors()
    return (
        "QPushButton {{ padding: {padding}; border: 1px solid {control_border}; border-radius: {radius}px; "
        "background: {control_bg}; color: {text}; font-size: {font_size}px; "
        "min-width: {min_width}px; min-height: 20px; }}"
        "QPushButton:hover {{ background: {control_bg_hover}; border-color: {control_border_hover}; }}"
        "QPushButton:pressed {{ background: rgba(0,0,0,0.10); }}"
        "QPushButton:checked {{ background: {accent_bg}; border-color: {accent}; color: {accent}; }}"
        "QPushButton:disabled {{ color: {text_faint}; background: transparent; border-color: {border}; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _btn_primary_style(min_width=80, padding="6px 16px", radius=8, font_size=13):
    """主题感知的主强调按钮样式：实心强调色，hover/pressed 加深。"""
    c = _rss_colors()
    return (
        "QPushButton {{ padding: {padding}; border: none; border-radius: {radius}px; "
        "background: {accent}; color: #ffffff; font-size: {font_size}px; font-weight: bold; "
        "min-width: {min_width}px; min-height: 20px; }}"
        "QPushButton:hover {{ background: {accent_hover}; }}"
        "QPushButton:pressed {{ background: {accent_pressed}; }}"
        "QPushButton:disabled {{ background: {text_faint}; color: #aaaaaa; }}"
    ).format(**c, min_width=min_width, padding=padding, radius=radius, font_size=font_size)


def _sidebar_qss():
    """主题感知的侧边栏列表样式：圆角条目 + hover/选中高亮。"""
    c = _rss_colors()
    return (
        "QListWidget {{ background: {panel}; border-right: 1px solid {border}; "
        "font-size: 12px; border-top: none; border-left: none; border-bottom: none; }}"
        "QListWidget::item {{ margin: 0px 3px; border-radius: 6px; }}"
        "QListWidget::item:hover {{ background: {row_hover}; }}"
        "QListWidget::item:selected {{ background: {row_selected}; color: {title_unread}; }}"
        "QListWidget::item:selected:hover {{ background: {row_selected}; }}"
        "QPushButton {{ font-size: 12px; padding: 4px 10px; }}"
    ).format(**c)


def _rss_card_style(radius=9):
    """组件样式：卡片/汇总面板（_MetricCard 对称）——圆角半透明面板 + 细边框。"""
    c = _rss_colors()
    return (
        "QFrame#rss_card {{ background: {card_bg}; border: 1px solid {card_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_ctrl_style(radius=8):
    """组件样式：控件容器（_ctrl_frame_style 对称）——输入/下拉等控件的宿主面板。"""
    c = _rss_colors()
    return (
        "QFrame#rss_ctrl {{ background: {ctrl_bg}; border: 1px solid {ctrl_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_head_style(radius=8):
    """组件样式：分组框/浮动标题（_group_box_style 对称）——浮动标题 + 柔底面板。"""
    c = _rss_colors()
    return (
        "QGroupBox {{ border: 1px solid {group_border}; border-radius: {radius}px; "
        "background: {group_bg}; margin-top: 16px; padding: 10px 8px 8px 8px; }}"
        "QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; "
        "left: 12px; top: 3px; padding: 0 6px; color: {text_primary}; }}"
    ).format(**c, radius=radius)


def _rss_btn_group_style(radius=8, spacing_hint=None):
    """组件样式：按钮组容器——内聚的圆角分组，内部控件透明承底。

    spacing_hint 仅作文档提示（布局间距由调用方 QHBoxLayout/QVBoxLayout 设置）。
    """
    c = _rss_colors()
    return (
        "QFrame#rss_btn_group {{ background: {btn_group_bg}; border: 1px solid {btn_group_border}; "
        "border-radius: {radius}px; }}"
    ).format(**c, radius=radius)


def _rss_menu_style(radius=8):
    """组件样式：下拉菜单——柔和悬浮/选中态（D9 下拉菜单项美化）。"""
    c = _rss_colors()
    return (
        "QMenu {{ background: {menu_bg}; border: 1px solid {menu_border}; "
        "border-radius: {radius}px; padding: 4px; }}"
        "QMenu::item {{ padding: 5px 22px 5px 10px; border-radius: 6px; "
        "background: transparent; color: {text}; }}"
        "QMenu::item:selected {{ background: {menu_item_selected}; color: {text_primary}; }}"
        "QMenu::item:disabled {{ color: {text_faint}; }}"
        "QMenu::separator {{ height: 1px; background: {divider}; margin: 4px 8px; }}"
    ).format(**c, radius=radius)
