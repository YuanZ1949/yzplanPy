"""RSS 样式：按钮/侧栏 QSS 生成。"""

from .text_utils import _rss_colors

def _btn_style(min_width=70, padding="6px 16px", radius=8, font_size=13):
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


def _btn_primary_style(min_width=70, padding="6px 16px", radius=8, font_size=13):
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
        "QListWidget::item {{ height: 28px; padding-left: 8px; margin: 1px 4px; border-radius: 6px; }}"
        "QListWidget::item:hover {{ background: {row_hover}; }}"
        "QListWidget::item:selected {{ background: {row_selected}; color: {title_unread}; }}"
        "QListWidget::item:selected:hover {{ background: {row_selected}; }}"
        "QPushButton {{ font-size: 12px; padding: 4px 10px; }}"
    ).format(**c)
