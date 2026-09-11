"""win_maintenance 模块入口：MODULE_INFO 与 Module。"""
from ..base import ModuleBase

MODULE_INFO = {
    "id": "win_maintenance",
    "name": "Windows维护",
    "description": "Windows系统日志查看与过滤",
}


class Module(ModuleBase):
    MODULE_ID = "win_maintenance"
    MODULE_NAME = "Windows维护"
    MODULE_DESCRIPTION = "Windows系统日志查看与过滤"
    ENABLED_BY_DEFAULT = True

    def create_home_widget(self, parent):
        from .home import _make_home_widget
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        from .page import _make_page_widget
        return _make_page_widget(self, parent)