"""right_menu 模块入口：MODULE_INFO 与 Module。

`_home_timer/_home_widget` 是首页小卡的生命周期钩子（见 router_admin/module.py
同款结构），定时器与卡片接线在 UI 层就绪后补齐；在此之前 `start/stop` 只透传
基类，`create_home_widget/create_page` 返回 None。

**本文件不得 import Qt**：包级 `__getattr__` 是惰性代理，本文件是它唯一的取值
目标；一旦这里 import Qt，早退路径（`--version`/`--help`/提权作业）就会被迫加载 Qt。
"""
from ..base import ModuleBase

MODULE_INFO = {
    "id": "right_menu",
    "name": "右键菜单",
    "description": "管理 Windows 资源管理器右键菜单：一键扫描文件/文件夹/桌面背景/驱动器"
                   "四类右键项与「新建」菜单项并展示名称/图标/命令/来源；隐藏或恢复已有"
                   "右键项（HKCU 直写，HKLM 自动 UAC 提权）；经典菜单总开关（Win11 右键切回"
                   "Win10 经典样式，可重启资源管理器生效）；「新建」菜单项的隐藏/恢复与"
                   "自定义模板新增；自定义右键项（运行命令或程序、打开网址与文件、多级"
                   "子菜单、按扩展名或条件限定）；为系统右键加「YZplan」级联子菜单"
                   "（快捷动作 + 打开管理器入口）；并提供 MCP 工具切片供外部查询与写入",
}


class Module(ModuleBase):
    MODULE_ID = "right_menu"
    MODULE_NAME = "右键菜单"
    MODULE_DESCRIPTION = MODULE_INFO["description"]
    MODULE_VERSION = "0.1"
    ENABLED_BY_DEFAULT = True

    def __init__(self, context):
        super().__init__(context)
        # 首页小卡的生命周期钩子：接上定时器与卡片实例后才有值
        self._home_timer = None
        self._home_widget = None

    # ── 生命周期（UI 层就绪后在 super 之后补定时器/卡片接线）────────
    def start(self):
        super().start()

    def stop(self):
        super().stop()

    # ── 宿主契约（UI 层就绪后替换为惰性 import widgets）─────────────
    def create_home_widget(self, parent):
        return None

    def create_page(self, parent):
        return None

    # ── YZplan 系统右键子菜单动作分发 ──────────────────────────────
    def dispatch_menu_action(self, action):
        """系统右键子菜单动作分发：返回 True 表示已处理该 action。"""
        return False
