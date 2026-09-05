"""全局主题：统一调控 qfluentwidgets 与普通 Qt 组件的浅色/深色，支持壁纸与毛玻璃。"""
import os

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .base import _wallpaper_pixmap, get_wallpaper, load_wallpaper, resolve_dark
from .font import _BASE_FONT_SIZE, ConfigHolder, apply_font_scale, current_font_scale
from .blur import _WP_CACHE, _blur_pixmap
from .glass import _WP_GLASS_CACHE, paint_wallpaper_glass
from .plain import paint_wallpaper
from .app_theme import apply_app_theme
from .qss_dark import _apply_dark_sheet
from .qss_light import _apply_light_sheet
from .styles import apply_global_stylesheet

__all__ = [
    "_wallpaper_pixmap",
    "resolve_dark",
    "load_wallpaper",
    "get_wallpaper",
    "_BASE_FONT_SIZE",
    "current_font_scale",
    "ConfigHolder",
    "apply_font_scale",
    "_WP_CACHE",
    "_blur_pixmap",
    "_WP_GLASS_CACHE",
    "paint_wallpaper_glass",
    "paint_wallpaper",
    "apply_app_theme",
    "apply_global_stylesheet",
    "_apply_dark_sheet",
    "_apply_light_sheet",
]