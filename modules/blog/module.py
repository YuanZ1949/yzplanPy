"""blog 模块入口：MODULE_INFO 与 Module。"""
from ..base import ModuleBase
from .store import _get_conn

MODULE_INFO = {
    "id": "blog",
    "name": "Blog",
    "description": "Markdown 博客文章编写与存储",
}


class Module(ModuleBase):
    MODULE_ID = "blog"
    MODULE_NAME = "Blog"
    MODULE_DESCRIPTION = "Markdown 博客文章编写与存储"
    ENABLED_BY_DEFAULT = True

    def start(self):
        super().start()
        _get_conn()

    def create_home_widget(self, parent):
        return None

    def create_page(self, parent):
        from .page import _make_page_widget
        return _make_page_widget(self, parent)