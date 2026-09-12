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
    padding = {"sm": sz["btn_padding_sm"], "md": sz["btn_padding_md"], "lg": sz["btn_padding_lg"]}[size]
    radius = sz["radius_md"]

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
        f" border-radius: {radius}px; padding: {padding}; font-size: {sz['font_size_sm']}px; }}"
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
        f" padding: {sz['input_height'] // 5}px 10px; font-size: {sz['font_size_sm']}px; }}"
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
    w.setStyleSheet(
        f"QComboBox {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: 4px 10px; font-size: {sz['font_size_sm']}px; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
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
    }[kind]
    bg, fg = style
    w = QtWidgets.QLabel(text, parent)
    w.setStyleSheet(
        f"QLabel {{ font-size: {sz['font_size_xs']}px; font-weight: 600;"
        f" padding: {sz['radius_sm'] // 2}px {sz['btn_padding_sm'].split()[1]};"
        f" border-radius: {sz['radius_sm'] + 10}px; background: {bg}; color: {fg}; }}"
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