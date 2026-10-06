"""right_menu.widgets.page_tabs：详情页的五个标签。

本包只 re-export 已落地的标签类；**标签清单本身不归这里管**——页面的标签顺序与标题由
`page._TABS` 驱动（新增标签时在那一处加一行）。`__all__` 只是「本包导出了谁」的显式
声明：后续任务把 ClassicTab / CustomTab / SettingsTab 落成真实现时，在这里补 import 与
`__all__`。
"""
from .scan_tab import ScanTab
from .shellnew_tab import ShellNewTab

__all__ = ["ScanTab", "ShellNewTab"]