"""proxy_ctrl 模块入口：MODULE_INFO 与 Module。

Module 实例承载**首页小卡共享的快照**（上次读到的代理地址、已启用目标数、已读取
标记）与读取时间戳。这些必须是实例属性而不是模块全局：同一进程里可能存在多个
Module（主窗口 + 独立模块窗 + 测试），模块全局会互相覆盖，导致首页显示别的实例
读到的地址。
"""
import logging

from core.qt_bootstrap import import_qt

from ..base import ModuleBase

_, QtCore, _, _ = import_qt()

from .widgets.home_widget import HOME_INTERVAL_MS, ProxyHomeWidget
from .widgets.page import ProxyPage

logger = logging.getLogger(__name__)

MODULE_INFO = {
    "id": "proxy_ctrl",
    "name": "代理控制",
    "description": "一键切换本机全局代理（Git / cURL / wget / Python / Node.js / "
                   "Docker，写入 HKCU 环境变量并广播），并可扫描局域网内的可用代理、"
                   "测速与记录历史",
}


class Module(ModuleBase):
    MODULE_ID = "proxy_ctrl"
    MODULE_NAME = "代理控制"
    MODULE_DESCRIPTION = MODULE_INFO["description"]
    MODULE_VERSION = "0.1"
    ENABLED_BY_DEFAULT = True

    def __init__(self, context):
        super().__init__(context)
        # 首页小卡的数据源（详情页读取后写入，本页只读）
        self.snapshot = {}
        # 上次读取状态的时刻（ms），用于首页限频，见 home_widget.HOME_INTERVAL_MS
        self.last_read_ms = 0
        self._home_timer = None
        self._home_widget = None

    def record_targets(self, rows):
        """详情页读完目标后调用，更新首页快照。"""
        from .widgets.home_widget import home_summary

        self.snapshot = dict(self.snapshot or {}, tried=True, **home_summary(rows))
        self._refresh_home()

    # ── 生命周期 ────────────────────────────────────────────────
    def start(self):
        super().start()
        logger.info("模块启动：%s", self.MODULE_ID)
        if self._home_timer is None:
            self._home_timer = QtCore.QTimer()
            self._home_timer.setInterval(HOME_INTERVAL_MS)
            self._home_timer.timeout.connect(self._home_tick)
            self._home_timer.start()

    def stop(self):
        if self._home_timer is not None:
            try:
                self._home_timer.stop()
            except RuntimeError:
                pass
            self._home_timer = None
        widget = self._home_widget
        if widget is not None:
            try:
                widget._stop()
            except RuntimeError:
                pass
        super().stop()
        logger.info("模块停止：%s", self.MODULE_ID)

    def _home_tick(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget.tick()
        except RuntimeError:
            self._home_widget = None

    def _refresh_home(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget._render()
        except RuntimeError:      # C++ 对象已析构
            self._home_widget = None

    # ── 宿主契约 ────────────────────────────────────────────────
    def create_home_widget(self, parent):
        widget = ProxyHomeWidget(self, parent)
        widget.destroyed.connect(self._on_home_destroyed)
        self._home_widget = widget
        self._refresh_home()
        return widget

    def create_page(self, parent):
        return ProxyPage(self, parent)

    def _on_home_destroyed(self, *_args):
        if self._home_timer is not None:
            try:
                self._home_timer.stop()
            except RuntimeError:
                pass
        self._home_widget = None
