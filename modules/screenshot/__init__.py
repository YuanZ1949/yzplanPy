# Screenshot module for YZplan
# Provides window capture, HTML rendering, and region screenshot capabilities

from .screenshot_core import ScreenshotCore
from .screenshot_ui import ScreenshotWidget
from .module import MODULE_INFO, Module

__all__ = ['ScreenshotCore', 'ScreenshotWidget', 'MODULE_INFO', 'Module']
