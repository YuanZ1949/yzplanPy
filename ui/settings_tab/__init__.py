"""程序设置选项卡：主题、壁纸、毛玻璃、开机自启、关闭行为、日志。"""
import os

from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, PushButton, StrongBodyLabel, SwitchButton

_, QtCore, QtGui, QtWidgets = import_qt()

from .core import _MCPBridge, SettingsTab
from .rows import SettingsTab
from .mcp import SettingsTab
from .log_build import SettingsTab
from .log_ops import SettingsTab
from .config import SettingsTab

__all__ = ["SettingsTab"]