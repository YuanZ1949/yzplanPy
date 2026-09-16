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
        # 首次启动时写入 enabled 标记，便于 MCP module_list 识别
        cfg = self.context.config
        if cfg.get("modules.screenshot") is None:
            cfg.set_module_enabled("screenshot", True)
        logger.info("截图模块已启动")

    def stop(self):
        super().stop()
        logger.info("截图模块已停止")

    def create_page(self, parent):
        """创建截图工具页面。"""
        self._widget = ScreenshotWidget(parent, context=self.context)
        return self._widget

    def create_settings_widget(self, parent):
        """创建独立可复用的截图设置面板（模块管理页入口）。"""
        from .screenshot_settings import _SettingsTab
        return _SettingsTab(
            parent, self.context, self.core,
            None, self._on_hotkey_triggered)

    def _on_hotkey_triggered(self):
        """模块管理页热键回调：立即全屏截图。"""
        self.core.capture_full_screen()
