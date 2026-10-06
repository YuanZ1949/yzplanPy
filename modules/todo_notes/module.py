"""todo_notes 模块入口：MODULE_INFO 与 Module。"""
import logging

from ..base import ModuleBase
from ..todo_store import _get_conn
from .home import _make_home_widget
from .page_widget import _make_page_widget
logger = logging.getLogger(__name__)
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
        logger.info("模块启动：%s", self.MODULE_ID)

    def stop(self):
        super().stop()
        logger.info("模块停止：%s", self.MODULE_ID)

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)
