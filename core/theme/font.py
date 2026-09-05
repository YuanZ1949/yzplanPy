"""全局字体缩放与 ConfigHolder。"""

_BASE_FONT_SIZE = 9


def current_font_scale():
    return ConfigHolder.scale


class ConfigHolder:
    scale = 1.0
    families = ["Microsoft YaHei", "Segoe UI", "PingFang SC"]


def apply_font_scale(scale):
    """按比例缩放全局基础字号（默认 9pt）。返回实际采用的 scale。"""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.7, min(1.6, scale))
    ConfigHolder.scale = scale
    from PySide6.QtGui import QFont
    from ..qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        return scale
    f = QtGui.QFont()
    f.setFamily(ConfigHolder.families[0])
    f.setPointSizeF(_BASE_FONT_SIZE * scale)
    app.setFont(f)
    from qfluentwidgets import setFont, setFontFamilies
    setFontFamilies(ConfigHolder.families)
    for w in app.allWidgets():
        try:
            w.update()
        except Exception:
            pass
    return scale
