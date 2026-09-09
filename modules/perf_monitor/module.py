"""perf_monitor 模块入口：MODULE_INFO 与 Module。"""
from ..base import ModuleBase
from .home import _make_home_widget
from .page import _make_page_widget
MODULE_INFO = {
    "id": "performance_meter",
    "name": "性能监测",
    "description": "监测 YZplan 进程资源占用与关键操作耗时，支持导出",
}

ENABLED_KEY = "performance.enabled"


class Module(ModuleBase):
    MODULE_ID = "performance_meter"
    MODULE_NAME = "性能监测"
    MODULE_DESCRIPTION = "监测 YZplan 进程资源占用与关键操作耗时，支持导出"
    ENABLED_BY_DEFAULT = True

    def start(self):
        super().start()
        from core.perf import set_enabled
        # 默认关闭耗时采集/函数采样器：sys.setprofile 会对每次函数调用产生
        # 采样开销，仅在用户在性能监测页显式开启后才激活。
        enabled = self.context.config.module_setting(self.id, "enabled", False)
        set_enabled(enabled)

    def stop(self):
        super().stop()

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)
