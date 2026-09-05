"""主题基础：深浅色判定与壁纸加载。"""
import os
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_wallpaper_pixmap = None


def resolve_dark(mode):
    """mode: auto / light / dark -> boolean dark"""
    if mode == "dark":
        return True
    if mode == "light":
        return False
    from qfluentwidgets import Theme, qconfig
    return qconfig.theme is Theme.DARK


def load_wallpaper(path):
    global _wallpaper_pixmap
    if path and os.path.isfile(path):
        _wallpaper_pixmap = QtGui.QPixmap(path)
        if _wallpaper_pixmap.isNull():
            _wallpaper_pixmap = None
    else:
        _wallpaper_pixmap = None
    return _wallpaper_pixmap


def get_wallpaper():
    return _wallpaper_pixmap
