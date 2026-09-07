"""截图模块 - 提供窗口截图、HTML 截图、区域截图等功能。"""

import logging
from ..base import ModuleBase
from .screenshot_core import ScreenshotCore
from .screenshot_ui import ScreenshotWidget

logger = logging.getLogger("screenshot")

MODULE_INFO = {
    "id": "screenshot",
    "name": "截图工具",
    "description": "支持窗口截图、HTML 截图、区域截图等功能",
}


class Module(ModuleBase):
    MODULE_ID = "screenshot"
    MODULE_NAME = "截图工具"
    MODULE_DESCRIPTION = "支持窗口截图、HTML 截图、区域截图等功能"
    MODULE_VERSION = "1.0"
    ENABLED_BY_DEFAULT = True

    def __init__(self, context):
        super().__init__(context)
        self.core = ScreenshotCore()
        self._widget = None

    def start(self):
        super().start()
        logger.info("截图模块已启动")

    def stop(self):
        super().stop()
        logger.info("截图模块已停止")

    def create_page(self, parent):
        """创建截图工具页面。"""
        self._widget = ScreenshotWidget(parent)
        return self._widget
