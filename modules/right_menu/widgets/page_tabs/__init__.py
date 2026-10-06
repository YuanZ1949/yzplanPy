"""right_menu.widgets.page_tabs：详情页的五个标签。

`__all__` 是这张表的**唯一真源**：页面只按 `__all__` 逐个 import 并 addTab，后续任务
把 ShellNewTab / ClassicTab / CustomTab / SettingsTab 落成真实现时，往这里追加即可，
页面代码不必再改（漏改 `__all__` 会让标签数不对——测试钉死了 5 个）。
"""
from .scan_tab import ScanTab

__all__ = ["ScanTab"]
