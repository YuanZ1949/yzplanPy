"""系统托盘：QSystemTrayIcon + 分组菜单（显示/隐藏、RSS 快捷、模块、更多/退出）。"""

import os
from ..qt_bootstrap import import_qt
from ..constants import ICON_PATH

PySide6, QtCore, QtGui, QtWidgets = import_qt()

from .tray_base import Tray
from .dialogs import Tray
from .mcp import Tray

__all__ = ["Tray"]