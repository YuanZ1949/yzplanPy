"""todo_notes 模块入口：MODULE_INFO 与 Module。"""
from ..base import ModuleBase
from ..todo_store import _get_conn
from .home import _make_home_widget
from .page_widget import _make_page_widget
MODULE_INFO = {
    "id": "todo_notes",
    "name": "便签待办",
    "description": "待办事项管理，支持优先级和截止日期",
}


class Module(ModuleBase):
    MODULE_ID = "todo_notes"
    MODULE_NAME = "便签待办"
    MODULE_DESCRIPTION = "待办事项管理，支持优先级和截止日期"
    ENABLED_BY_DEFAULT = True

    def start(self):
        super().start()
        _get_conn()

    def stop(self):
        super().stop()

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)
