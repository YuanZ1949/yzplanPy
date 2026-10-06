"""right_menu 模块入口：MODULE_INFO 与 Module。

**本文件必须保持 Qt-free**：registry 的模块发现（`getattr(MODULE_INFO)` +
`getattr(Module)`）必须能在任何 Qt 导入之前完成——本应用预留的 `--elevated-job`
提权作业通道（后续接入）会在一切 Qt import 之前走模块发现，而该 `getattr` 会经
PEP 562 代理加载本文件。因此 widgets（首页卡/页面控件）import Qt，它们的 import
以及 `start()` 里的 `QTimer` 必须**全部留在函数体内**，绝不放模块顶层。
`tests/test_right_menu_ui.py::test_lazy_export_stays_qt_free_in_fresh_process`
在全新子进程里守卫这条不变式，改动本文件必须重跑它。

生命周期（`start/stop` 建停 `HOME_INTERVAL_MS` 定时器、`create_home_widget` 建卡、
`create_page` 建详情页）的结构参照 proxy_ctrl/module.py，但与那个文件的关键区别是：
**本文件不在模块顶层 import Qt**——proxy_ctrl 与 router_admin 都在顶层 import Qt，
不要照抄它们的 import 段。
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
        # 首页小卡的生命周期钩子：start() 建表、create_home_widget 建卡后才有值
        self._home_timer = None
        self._home_widget = None

    # ── 生命周期（30s 定时器驱动首页小卡的 tick）────────────────
    def start(self):
        super().start()
        # QTimer 与 home_widget 都在函数内 import：模块顶层必须保持 Qt-free
        from core.qt_bootstrap import import_qt

        from .widgets.home_widget import HOME_INTERVAL_MS

        if self._home_timer is None:
            _, QtCore, _, _ = import_qt()
            self._home_timer = QtCore.QTimer()
            self._home_timer.setInterval(HOME_INTERVAL_MS)
            self._home_timer.timeout.connect(self._home_tick)
            self._home_timer.start()

    def stop(self):
        if self._home_timer is not None:
            try:
                self._home_timer.stop()
            except RuntimeError:                  # C++ 对象已析构
                pass
            self._home_timer = None
        widget = self._home_widget
        if widget is not None:
            try:
                widget._stop()
            except RuntimeError:                  # C++ 对象已析构
                pass
        super().stop()

    def _home_tick(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget.tick()
        except RuntimeError:                      # C++ 对象已析构
            self._home_widget = None

    def _refresh_home(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget._render()
        except RuntimeError:                      # C++ 对象已析构
            self._home_widget = None

    # ── 宿主契约（惰性 import widgets：保持顶层 Qt-free）─────────
    def create_home_widget(self, parent):
        # 函数内 import widgets：模块顶层必须保持 Qt-free（见本文件 docstring）
        from .widgets.home_widget import RightMenuHomeWidget

        widget = RightMenuHomeWidget(self, parent)
        widget.destroyed.connect(self._on_home_destroyed)
        self._home_widget = widget
        self._refresh_home()
        return widget

    def create_page(self, parent):
        # 函数内 import widgets：模块顶层必须保持 Qt-free（见本文件 docstring）
        from .widgets.page import RightMenuPage

        return RightMenuPage(self, parent)

    def _on_home_destroyed(self, *_args):
        if self._home_timer is not None:
            try:
                self._home_timer.stop()
            except RuntimeError:
                pass
        self._home_widget = None

    # ── YZplan 系统右键子菜单动作分发 ──────────────────────────────
    def dispatch_menu_action(self, action):
        """系统右键子菜单动作分发：返回 True 表示已处理该 action。"""
        return False
