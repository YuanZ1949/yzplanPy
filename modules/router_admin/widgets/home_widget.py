"""router_admin 首页小卡：在线状态点 + 运行时长 + WAN IP + 在线终端数 + 打开。

刷新节奏比详情页保守：详情页默认 5 秒（用户交互），首页 15 秒（无人值守，
不该频繁打扰路由器）。且**必须走后台线程**：一次 telnet 登录 1~3 秒，
放主页渲染路径会让整页滚动卡住。口令缺失时不轮询（没什么可连的）。

数据源统一是 `Module.snapshot`（详情页与本页共用），本页只读不改——
`snapshot["online"]` 由 owner 的 mark_online/mark_offline 维护。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_label, make_status_chip, make_tool_button

from .. import parsers, store
from ..connection import ConnectionParams
from ..workers import TaskGroup

_, QtCore, QtGui, QtWidgets = import_qt()

#: 首页轮询间隔（ms）：比详情页保守，避免无人值守时频繁打扰路由器
HOME_INTERVAL_MS = 15000
#: 概览采集里首页只需要这 6 条命令
HOME_COMMANDS = ("cat /proc/uptime", "ifconfig -a", "cat /proc/net/arp")


def home_summary(data, wan_iface="pppoe-wan"):
    """一次采集结果 → 首页卡片要的四项（与总览共用解析层，不重复实现）。"""
    uptime = parsers.parse_uptime(data.get("uptime") or "")
    ifaces = parsers.parse_ifconfig(data.get("ifconfig") or "")
    arp = parsers.parse_arp(data.get("arp") or "")
    wan = next((row for row in ifaces if row.get("iface") == wan_iface), {})
    return {
        "uptime_s": (uptime or {}).get("uptime_s"),
        "wan_ip": wan.get("inet") or "—",
        "clients": sum(1 for row in arp if row.get("complete")),
    }


def home_collect(session):
    """后台只读采集（3 条命令，不做速率/CPU 差值，首页不需要）。"""
    out = session.run_batch(HOME_COMMANDS)
    return {"uptime": out[0], "ifconfig": out[1], "arp": out[2]}


class RouterHomeWidget(QtWidgets.QWidget):
    """首页小卡。`tick()` 由 Module 的 15s 定时器驱动（后台线程采集）。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = TaskGroup(self)
        self.setMinimumWidth(220)
        lay = QtWidgets.QVBoxLayout(self)
        pad = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(sizing()["radius_xs"])

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(sizing()["radius_xs"])
        head.addWidget(make_label("路由器", role="caption", parent=self))
        self.chip = None
        self._chip_kind = None
        self._chip_slot = head
        head.addStretch(1)
        self.btn_open = make_tool_button("打开", kind="ghost", size="sm",
                                         parent=self)
        self.btn_open.clicked.connect(self._open)
        head.addWidget(self.btn_open)
        lay.addLayout(head)

        self.lb_wan = self._add_row("WAN", "—")
        self.lb_up = self._add_row("运行", "—")
        self.lb_clients = self._add_row("终端", "—")
        self.destroyed.connect(self._stop)
        self._render()

    def _add_row(self, name, value):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label(name, role="caption", parent=self))
        lb = make_label(value, role="body", parent=self)
        lb.setMinimumWidth(sizing()["btn_min_width"])
        row.addWidget(lb)
        row.addStretch(1)
        self.layout().addLayout(row)
        return lb

    def _set_chip(self, text, kind):
        if kind == self._chip_kind and self.chip is not None:
            self.chip.setText(text)
            return
        self._chip_kind = kind
        old = self.chip
        self.chip = make_status_chip(text, kind=kind, parent=self)
        self._chip_slot.insertWidget(1, self.chip)
        if old is not None:
            old.setParent(None)
            old.deleteLater()

    def _render(self):
        """按 owner.snapshot 重绘卡片（纯本地渲染，无网络）。"""
        snap = self._owner.snapshot or {}
        if snap.get("online"):
            self._set_chip("在线", "success")
        elif snap.get("tried"):
            self._set_chip("离线", "error")
        else:
            self._set_chip("未连接", "info")
        self.lb_wan.setText(str(snap.get("wan_ip") or "—"))
        self.lb_up.setText(parsers.parse_uptime_fmt(snap.get("uptime_s")))
        self.lb_clients.setText(f"{snap.get('clients', 0)} 个")

    def tick(self):
        """定时器回调：无口令 / 上一轮未结束就跳过，绝不在主线程连路由器。"""
        if self._group.busy:
            return False
        settings = store.load()
        if not settings.get("password"):
            return False
        self._group.set_params(ConnectionParams.from_settings(settings))
        return self._group.start(home_collect, on_ok=self._applied,
                                 on_err=self._failed, label="home")

    def _applied(self, data):
        summary = home_summary(data, self._owner.wan_iface)
        self._owner.snapshot = dict(self._owner.snapshot or {}, online=True,
                                    tried=True, **summary)
        self._render()

    def _failed(self, kind, text):
        self._owner.snapshot = dict(self._owner.snapshot or {}, online=False,
                                    tried=True)
        self._render()
        self.setToolTip(f"最近一次采集失败（{kind}）：{text}")

    def _open(self, *_args):
        from ui.module_pages import open_module_page
        try:
            open_module_page(self._owner, self)
        except RuntimeError:
            pass

    def _stop(self):
        """销毁即停：中断并 join 线程，避免悬挂 QThread 让 pytest 永不退出。"""
        try:
            self._group.shutdown()
        except RuntimeError:
            pass
