"""right_menu.widgets.page_tabs：详情页的五个标签。

本包只 re-export 已落地的标签类；**标签清单本身不归这里管**——页面的标签顺序与标题由
`page._TABS` 驱动（新增标签时在那一处加一行）。`__all__` 只是「本包导出了谁」的显式声明：
五个标签全部是真实实现（装配层已无占位标签）。
"""
from .classic_tab import ClassicTab
from .custom_tab import CustomTab
from .scan_tab import ScanTab
from .settings_tab import SettingsTab
from .shellnew_tab import ShellNewTab

__all__ = ["ClassicTab", "CustomTab", "ScanTab", "SettingsTab", "ShellNewTab"]
