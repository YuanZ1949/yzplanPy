"""全局样式入口。"""
from .base import resolve_dark
from .qss_dark import _apply_dark_sheet
from .qss_light import _apply_light_sheet

def apply_global_stylesheet(acrylic=False, dark=None):
    """全局 QSS：卡片圆角、滚动条、按钮、输入框等，适配浅色/深色。"""
    if dark is None:
        dark = resolve_dark("auto")

    if dark:
        _apply_dark_sheet(acrylic)
    else:
        _apply_light_sheet(acrylic)
