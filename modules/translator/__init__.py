"""translator 模块：在线翻译与语音识别实时翻译。"""
from .module import MODULE_INFO, Module
from .translator_core import translate_text, LANGUAGES
from .home import _make_home_widget

__all__ = [
    "MODULE_INFO",
    "Module",
    "translate_text",
    "LANGUAGES",
    "_make_home_widget",
]