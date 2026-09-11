"""perf_monitor 模块入口：MODULE_INFO 与 Module。"""
import collections
from ..base import ModuleBase
from core.qt_bootstrap import import_qt
_, QtCore, _, _ = import_qt()
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

    def __init__(self, context):
        super().__init__(context)
        # owner 级共享数据 deque：跨页面开/关保留 CPU/内存历史（近 4 分钟，2s×120）。
        self._shared_cpu_data = collections.deque(maxlen=120)
        self._shared_mem_data = collections.deque(maxlen=120)
        self._shared_listeners = []
        self._shared_timer = None

    def _shared_tick(self):
        """2s 定时回调：采集资源并 append 到共享 deque，再通知监听者。"""
        from .proc import _proc_resources
        try:
            r = _proc_resources()
            cpu = r["cpu"]
            mem = r["memory_mb"]
        except Exception:
            cpu = 0.0
            mem = 0.0
        self._shared_cpu_data.append(cpu)
        self._shared_mem_data.append(mem)
        for cb in list(self._shared_listeners):
            try:
                cb(cpu, mem)
            except Exception:
                pass

    def register_shared_listener(self, callback):
        """注册共享数据监听（页面图表实时更新回调）。"""
        self._shared_listeners.append(callback)

    def unregister_shared_listener(self, callback):
        """注销共享数据监听（页面销毁时调用，避免 dangling 回调）。"""
        try:
            self._shared_listeners.remove(callback)
        except ValueError:
            pass

    def start(self):
        super().start()
        from core.perf import set_enabled
        # 默认关闭耗时采集/函数采样器：sys.setprofile 会对每次函数调用产生
        # 采样开销，仅在用户在性能监测页显式开启后才激活。
        enabled = self.context.config.module_setting(self.id, "enabled", False)
        set_enabled(enabled)
        # 模块级 2s 共享采集定时器：持续喂给共享 deque，页面重开即有历史。
        self._shared_timer = QtCore.QTimer()
        self._shared_timer.setInterval(2000)
        self._shared_timer.timeout.connect(self._shared_tick)
        self._shared_timer.start()

    def stop(self):
        if self._shared_timer is not None:
            try:
                self._shared_timer.stop()
            except RuntimeError:
                pass
            self._shared_timer = None
        super().stop()

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)