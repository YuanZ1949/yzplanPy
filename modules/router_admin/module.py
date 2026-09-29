"""router_admin 模块入口：MODULE_INFO 与 Module。

Module 实例承载**跨页面共享的采样基线**（上一次的 /proc/net/dev 与 /proc/stat 文本、
采样时刻、LAN IP、首页快照）。这些必须是实例属性而不是模块全局：同一进程里可能
存在多个 Module（主窗口 + 独立模块窗 + 测试），模块全局会互相踩基线，导致网速
与 CPU 出现负值或除零。
"""
from core.qt_bootstrap import import_qt

from ..base import ModuleBase

_, QtCore, _, _ = import_qt()

from .widgets.home_widget import HOME_INTERVAL_MS, RouterHomeWidget
from .widgets.page import RouterPage

MODULE_INFO = {
    "id": "router_admin",
    "name": "路由器管理",
    "description": "监测小米路由器（OpenWrt/telnet）状态：WAN IP、运行时长、内存、"
                   "磁盘、在线终端、实时网速，并支持服务启停、无线开关、"
                   "配置编辑与重启（全部带二次确认与自动备份）",
}


class Module(ModuleBase):
    MODULE_ID = "router_admin"
    MODULE_NAME = "路由器管理"
    MODULE_DESCRIPTION = MODULE_INFO["description"]
    MODULE_VERSION = "0.1"
    ENABLED_BY_DEFAULT = True

    def __init__(self, context):
        super().__init__(context)
        # 差值采样基线（总览页写入，首页与详情页共用同一份）
        self.prev_net_dev = None
        self.prev_proc_stat = None
        self.prev_net_ts = None
        # 连接状态与首页卡片数据源
        self.state = "offline"
        self.snapshot = {}
        self.lan_ip = None
        self.wan_iface = "pppoe-wan"
        self.lan_iface = "br-lan"
        self._home_timer = None
        self._home_widget = None

    # ── 在线状态（首页小卡与详情页 chip 共用同一份判定）─────────
    def mark_online(self):
        self.state = "online"
        snap = dict(self.snapshot or {})
        snap.update({"online": True, "tried": True})
        self.snapshot = snap
        self._refresh_home()

    def mark_offline(self):
        self.state = "offline"
        snap = dict(self.snapshot or {})
        snap.update({"online": False, "tried": True})
        self.snapshot = snap
        self._refresh_home()

    def _refresh_home(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget._render()
        except RuntimeError:      # C++ 对象已析构
            self._home_widget = None

    # ── 生命周期 ────────────────────────────────────────────────
    def start(self):
        super().start()
        # 15s 定时器只驱动首页小卡（详情页有自己的时钟，且需用户先连接）。
        # 无口令时 tick() 会直接返回，不产生任何网络流量。
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

    def _home_tick(self):
        widget = self._home_widget
        if widget is None:
            return
        try:
            widget.tick()
        except RuntimeError:
            self._home_widget = None

    # ── 宿主契约 ────────────────────────────────────────────────
    def create_home_widget(self, parent):
        widget = RouterHomeWidget(self, parent)
        widget.destroyed.connect(self._on_home_destroyed)
        self._home_widget = widget
        self._refresh_home()
        return widget

    def create_page(self, parent):
        return RouterPage(self, parent)

    def _on_home_destroyed(self, *_args):
        if self._home_timer is not None:
            try:
                self._home_timer.stop()
            except RuntimeError:
                pass
        self._home_widget = None
