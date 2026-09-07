# Screenshot module for YZplan
# Provides window capture, HTML rendering, and region screenshot capabilities

from .screenshot_core import ScreenshotCore
from .screenshot_ui import ScreenshotWidget

__all__ = ['ScreenshotCore', 'ScreenshotWidget']
