"""统一控件工厂：所有控件的高度/颜色/字号取自 core.theme.tokens 令牌。

规则：工厂是唯一允许触碰令牌的代码区。调用方只传语义参数
（kind/size/role），禁止传入颜色值或像素尺寸。
"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.theme.tokens import sizing, theme_palette


def make_button(text, icon=None, *, kind="default", size="md", parent=None):
    p = theme_palette()
    sz = sizing()
    height = {"sm": sz["btn_height_sm"], "md": sz["btn_height_md"], "lg": sz["btn_height_lg"]}[size]
    pad_v = {"sm": sz["btn_padding_v_sm"], "md": sz["btn_padding_v_md"], "lg": sz["btn_padding_v_lg"]}[size]
    padding = {"sm": sz["btn_padding_sm"], "md": sz["btn_padding_md"], "lg": sz["btn_padding_lg"]}[size]
    radius = sz["radius_md"]
    # 盒模型单一真源：min-height + 2*纵向padding + 2*border(1px) == btn_height_*。
    # 行内 min-height 覆盖全局 QSS 的 QPushButton min-height，使渲染高度精确等于令牌。
    min_h = height - 2 * pad_v - 2

    # (bg, fg, border, hover, pressed)
    style = {
        "default": (p["bg_control"], p["text_primary"], p["border"], p["bg_hover"], p["overlay_pressed"]),
        "primary": (p["accent"], "#ffffff", p["accent"], p["accent_hover"], p["accent_pressed"]),
        "danger": (p["danger"], "#ffffff", p["danger"], p["danger_hover"], p["danger_pressed"]),
        "ghost": ("transparent", p["text_primary"], "transparent", p["bg_hover"], p["overlay_pressed"]),
        "flat": ("transparent", p["text_primary"], "transparent", "transparent", "transparent"),
    }[kind]
    bg, fg, border, hover, pressed = style

    btn = QtWidgets.QPushButton(text, parent)
    btn.setFixedHeight(height)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border};"
        f" border-radius: {radius}px; padding: {padding}; min-height: {min_h}px;"
        f" font-size: {sz['font_size_sm']}px; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
        f"QPushButton:pressed {{ background: {pressed}; }}"
    )
    if icon is not None:
        btn.setIcon(icon)
    return btn


def make_line_edit(placeholder="", *, parent=None):
    p = theme_palette()
    sz = sizing()
    w = QtWidgets.QLineEdit(parent)
    w.setPlaceholderText(placeholder)
    w.setFixedHeight(sz["input_height"])
    w.setStyleSheet(
        f"QLineEdit {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: {sz['input_height'] // 5}px {sz['input_h_padding']}px; font-size: {sz['font_size_sm']}px; }}"
        f"QLineEdit:focus {{ border: 1px solid {p['border_focus']}; }}"
    )
    return w


def make_combo(items=None, *, parent=None):
    p = theme_palette()
    sz = sizing()
    w = QtWidgets.QComboBox(parent)
    w.setFixedHeight(sz["combo_height"])
    if items:
        w.addItems(items)
    arrow_w = sz["combo_arrow_w"] // 2  # 三角左/右边框各占一半
    arrow_h = sz["combo_arrow_h"]
    w.setStyleSheet(
        f"QComboBox {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: {sz['combo_padding']}; font-size: {sz['font_size_sm']}px; }}"
        f"QComboBox::drop-down {{ border: none; width: {sz['combo_drop_width']}px; }}"
        f"QComboBox::down-arrow {{ image: none; width: 0; height: 0;"
        f" border-left: {arrow_w}px solid transparent;"
        f" border-right: {arrow_w}px solid transparent;"
        f" border-top: {arrow_h}px solid {p['text_secondary']}; }}"
        f"QComboBox QAbstractItemView {{ background: {p['qss_menu_bg']};"
        f" color: {p['text_primary']};"
        f" border: 1px solid {p['qss_menu_border']};"
        f" selection-background-color: {p['qss_menu_sel_bg']};"
        f" selection-color: {p['white']}; }}"
    )
    return w


def make_card(*, parent=None):
    p = theme_palette()
    sz = sizing()
    f = QtWidgets.QFrame(parent)
    f.setStyleSheet(
        f"QFrame {{ background: {p['bg_card']}; border: 1px solid {p['border']};"
        f" border-radius: {sz['radius_lg']}px; }}"
    )
    return f


def make_status_chip(text, *, kind="info", parent=None):
    p = theme_palette()
    sz = sizing()
    style = {
        "torrent": (p["chip_torrent_bg"], p["chip_torrent_fg"]),
        "article": (p["chip_article_bg"], p["chip_article_fg"]),
        "success": (p["bg_card"], p["success"]),
        "info": (p["bg_card"], p["info"]),
        "warning": (p["bg_card"], p["status_warning"]),
        "error": (p["bg_card"], p["status_error"]),
    }[kind]
    bg, fg = style
    w = QtWidgets.QLabel(text, parent)
    w.setStyleSheet(
        f"QLabel {{ font-size: {sz['font_size_xs']}px; font-weight: 600;"
        f" padding: {sz['radius_sm'] // 2}px {sz['chip_padding_h']}px;"
        f" border-radius: {sz['radius_sm'] + sz['chip_border_extra']}px; background: {bg}; color: {fg}; }}"
    )
    return w


def make_label(text, *, role="body", parent=None):
    p = theme_palette()
    sz = sizing()
    style = {
        "title": (sz["font_size_lg"], "700", p["text_primary"]),
        "subtitle": (sz["font_size_md"], "600", p["text_primary"]),
        "body": (sz["font_size_sm"], "400", p["text_primary"]),
        "caption": (sz["font_size_xs"], "400", p["text_secondary"]),
        "muted": (sz["font_size_xs"], "400", p["text_disabled"]),
    }[role]
    fs, weight, color = style
    w = QtWidgets.QLabel(text, parent)
    w.setStyleSheet(
        f"QLabel {{ font-size: {fs}px; font-weight: {weight}; color: {color};"
        f" background: transparent; }}"
    )
    return w