"""translator 模块入口：MODULE_INFO 与 Module。"""
from ..base import ModuleBase

MODULE_INFO = {
    "id": "translator",
    "name": "翻译工具",
    "description": "在线翻译与语音识别实时翻译",
}


class Module(ModuleBase):
    MODULE_ID = "translator"
    MODULE_NAME = "翻译工具"
    MODULE_DESCRIPTION = "在线翻译与语音识别实时翻译"
    ENABLED_BY_DEFAULT = True

    def create_home_widget(self, parent):
        from .home import _make_home_widget
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        from .page import _make_page_widget
        return _make_page_widget(self, parent)