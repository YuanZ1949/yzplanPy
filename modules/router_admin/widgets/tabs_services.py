"""router_admin.widgets.tabs_services：服务管理 Tab（服务启停 + 无线开关与自恢复）。

两条链路都必须二次确认 + 先自动备份。服务命令一律由 `services.py` 构造（它有
SERVICE_NAME_RE 注入防护），本文件**不拼** `/etc/init.d/<name>`；无线动作前先用
`wifi.build_rollback_arm_command()` 在路由器上挂一个脱绑的 `sleep 45; wifi up`，UI
显示「已挂 45 秒自动恢复」并提供「取消自动恢复」。无线关闭会切断本机 telnet。
"""
import time
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label

from .. import backup, services, wifi
from ..telnet import TelnetError
from ..workers import collect_services
from . import alert, confirm, make_card_block, notify
from .tables import cell_payload, fill_action_cell, fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

ACTION_CN = {"start": "启动", "stop": "停止", "restart": "重启",  # 动作 -> 中文
             "reload": "重载", "up": "启动", "down": "关闭"}
#: 服务名 -> 写操作前要备份的 /etc/config 节名（静态映射，非用户输入）
SERVICE_SECTION = {
    "network": "network", "netifd": "network", "pppd": "network",
    "firewall": "firewall", "dnsmasq": "dnsmasq", "odhcpd": "dhcp",
    "odhcp6c": "dhcp", "hostapd": "wireless", "wpad": "wireless",
    "sysntpd": "system", "uhttpd": "system",
}
_ACTION_BUTTONS = (("启动", "start"), ("停止", "stop"),   # 每行四个操作按钮
                   ("重启", "restart"), ("重载", "reload"))
_WIFI_BUTTONS = (("up", "启动无线"), ("down", "关闭无线"), ("restart", "重启无线"))
_CHIPS = {1: lambda r: (r["autostart"], "success" if r["on"] else "info")}
_TICK_MS, _BUSY = 1000, "尚未连接路由器或上一轮任务未结束。"


def service_action_text(name, action):
    """服务操作的二次确认文案。危险服务额外写明断网风险。"""
    head = f"即将对服务「{name}」执行「{ACTION_CN.get(action, action)}」操作。"
    risk = (f"\n\n{name} 属于高危服务，会直接影响路由器自身连通性：执行期间本机与"
            f"路由器的连接会中断，Wi-Fi 可能短暂消失，且无法从 YZplan 撤销。"
            if services.is_dangerous(name)
            else "\n\n执行后可在下方重新拉取列表确认结果。")
    return f"{head}{risk}\n\n已先自动备份相关配置。确认继续？"

def wifi_action_text(action):
    """无线操作的二次确认文案（必须写明 45 秒自恢复与断连风险）。"""
    if action == "up":
        return ("即将启动无线（wifi up）。\n\n无线立即开始广播，附近设备可能"
                "重新连入你的家庭网络。确认继续？")
    return (f"即将执行「{ACTION_CN.get(action, action)}」无线操作。\n\n"
            f"无线关闭后 AP 会消失，本机（走 br-lan 的 telnet）可能随即断开，"
            f"你可能再也连不回路由器。\n\n已先在路由器上挂起 {wifi.ROLLBACK_DELAY} 秒"
            f"自动恢复：不手动取消，路由器会在倒计时结束后自己 wifi up。\n\n确认继续？")

def service_action_worker(name, action, section):
    """后台执行一次服务动作（先自动备份对应节的配置，再下发动作）。"""
    def worker(session):
        saved = None
        if section:
            session.run(backup.build_remote_backup_command(section))
            saved = backup.save_backup(
                section, session.run(backup.build_remote_read_command(section)))
        return {"name": name, "action": action, "backup": saved,
                "output": session.run(services.build_action_command(name, action))}
    return worker

def wifi_query_worker(session):
    """无线状态 + 回滚挂起状态（一次会话两条命令）。

    必须用 `wifi.split_state_output` 拆两段：wl0/wl1 已被 enslaved 到 br-lan，
    自身不持 IPv4，`any_up` 只能靠 hostapd 判定。
    """
    ifconfig_text, ps_text = wifi.split_state_output(
        session.run(wifi.build_state_command()))
    return {"state": wifi.parse_wifi_state(ifconfig_text, ps_text), "rollback":
            wifi.parse_rollback_state(
                session.run(wifi.build_rollback_query_command()))}

def wifi_action_worker(action):
    """无线动作（down/restart 前先挂 45 秒自恢复回滚）。

    无线下线会掐断本会话：命令已送达、回滚已挂，故 TelnetError 按「已下发」处理。
    """
    def worker(session):
        armed = {"armed": False, "pid": None}
        if action != "up":
            armed = wifi.parse_arm_result(
                session.run(wifi.build_rollback_arm_command()))
        try:
            session.run(wifi.build_wifi_command(action))
            note = ""
        except TelnetError as exc:
            note = f"连接断开（{exc}），属无线关闭的预期表现。"
        return {"action": action, "armed": armed, "note": note}
    return worker

def wifi_cancel_worker(session):
    """按 PID 终止路由器上的自动恢复任务（`CANCELLED` 才算成功）。"""
    return {"cancelled": "CANCELLED" in
            (session.run(wifi.build_rollback_cancel_command()) or "").upper()}
class ServicesTab(QtWidgets.QWidget):
    """服务管理页：服务表 + 无线控制区（含 45 秒自动恢复提示与取消按钮）。"""
    def __init__(self, owner, group, *, parent=None):
        super().__init__(parent)
        self._owner, self._group, self._armed_at = owner, group, None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sizing()["dialog_spacing"])
        self.summary = make_label("尚未采集", role="subtitle", parent=self)
        btn = make_button("刷新列表", size="sm", parent=self)
        btn.clicked.connect(lambda: self.refresh())
        head = QtWidgets.QHBoxLayout()
        head.addWidget(self.summary)
        head.addStretch(1)
        head.addWidget(btn)
        lay.addLayout(head)
        self.table = make_table(("服务名", "开机自启", "操作"), parent=self,
                                min_height=sizing()["log_table_min_height"])
        lay.addWidget(self.table, 1)
        lay.addWidget(self._build_wifi())
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._on_tick)

    def _build_wifi(self):
        card, lay = make_card_block("无线", parent=self)
        btn = make_button("查询无线", size="sm", parent=card)
        btn.clicked.connect(self.refresh_wifi)
        self.wifi_state = make_label("状态未知", role="caption", parent=card)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(self.wifi_state)
        head.addStretch(1)
        head.addWidget(btn)
        lay.addLayout(head)
        self.wifi_hint = make_label(
            f"关闭/重启无线前会先在路由器上挂起 {wifi.ROLLBACK_DELAY} 秒自动恢复。",
            role="caption", parent=card)
        lay.addWidget(self.wifi_hint)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        self.wifi_btns = {}
        for action, text in _WIFI_BUTTONS:
            btn = make_button(text, size="sm", parent=card)
            btn.clicked.connect(lambda _=False, a=action: self._wifi_action(a))
            row.addWidget(btn)
            self.wifi_btns[action] = btn
        btn = make_button("取消自动恢复", kind="danger", size="sm", parent=card)
        btn.clicked.connect(self._cancel_rollback)
        row.addStretch(1)
        row.addWidget(btn)
        lay.addLayout(row)
        return card
    def set_connected(self, connected):
        for btn in self.wifi_btns.values():
            btn.setEnabled(bool(connected))
    def _start(self, worker, on_ok, label, denied=_BUSY):
        """统一的「起后台任务 + 忙时给可读提示」入口（防连打）。"""
        if self._group.start(worker, on_ok=on_ok, on_err=self._failed, label=label):
            return True
        notify(self, "无法执行", denied, error=True)
        return False

    def _failed(self, kind, text):
        self.summary.setText("采集失败")
        notify(self, "服务操作失败", text, error=True)
    def refresh(self):
        if not self._start(collect_services, self.apply_services, "collect"):
            return False
        self.summary.setText("采集中…")
        return True

    def apply_services(self, data):
        fill_table(self.table, data.get("rows") or [],
                   (("name", None), ("autostart", None), ("_ops", None)),
                   chips=_CHIPS, payload=lambda r: r["name"])
        for row in range(self.table.rowCount()):
            name = cell_payload(self.table, row)
            if name:
                actions = [(cn, (name, act)) for cn, act in _ACTION_BUTTONS]
                fill_action_cell(self.table, row, 2, actions, self._service_action)
        self.summary.setText(f"共 {self.table.rowCount()} 个服务")

    def _service_action(self, name, action):
        if not confirm(self, "确认服务操作", service_action_text(name, action),
                       ok_text=f"执行{ACTION_CN.get(action, action)}"):
            return
        self._start(service_action_worker(name, action, SERVICE_SECTION.get(name)),
                    self._action_done, f"{name} {action}")

    def _action_done(self, data):
        saved = data.get("backup")
        self.summary.setText(f"服务「{data.get('name')}」"
                             f"{ACTION_CN.get(data.get('action'), '')}已下发"
                             + (f"，配置已备份到 {saved}" if saved else ""))
        self.refresh()

    def refresh_wifi(self):
        self._start(wifi_query_worker, self._apply_wifi, "wifi_state")

    def _apply_wifi(self, data):
        state = data.get("state") or {}
        aps = [n for n, v in (state.get("ifaces") or {}).items() if v.get("inet")]
        self.wifi_state.setText(("无线开启" if state.get("any_up") else "无线关闭")
                                + f"（{', '.join(aps) or 'wlan 接口无 IPv4'}）")
        if (data.get("rollback") or {}).get("armed") and self._armed_at is None:
            self._armed_at, tick = time.time(), self._tick
            tick.start()
        self._on_tick()
    def _wifi_action(self, action):
        if not confirm(self, "确认无线操作", wifi_action_text(action),
                       ok_text=ACTION_CN.get(action, action)):
            return
        self._start(wifi_action_worker(action), self._wifi_applied, f"wifi {action}")

    def _wifi_applied(self, data):
        if (data.get("armed") or {}).get("armed"):
            self._armed_at, tick = time.time(), self._tick
            tick.start()
            self._on_tick()
        notify(self, "已下发", f"无线{ACTION_CN.get(data.get('action'), '')}命令已"
                              f"发送。已挂 {wifi.ROLLBACK_DELAY} 秒自动恢复。"
                              + (f"\n{data['note']}" if data.get("note") else ""))

    def _cancel_rollback(self):
        self._start(wifi_cancel_worker, self._cancel_done, "wifi_rollback_cancel")

    def _cancel_done(self, data):
        if not data.get("cancelled"):
            alert(self, "取消失败", "路由器上没有找到待执行的自动恢复任务。")
            return
        self._armed_at = None
        self._tick.stop()
        self.wifi_hint.setText("自动恢复已取消，无线不会自动开启。")
        notify(self, "已取消", "路由器上的自动恢复任务已终止。")

    def _on_tick(self):
        """倒计时提示。窗口过后不再承诺自愈，如实提示改用物理按键。"""
        if self._armed_at is None:
            return
        left = int(wifi.ROLLBACK_DELAY - (time.time() - self._armed_at))
        if left <= 0:
            self._armed_at = None
            self._tick.stop()
            self.wifi_hint.setText(f"{wifi.ROLLBACK_DELAY} 秒自恢复窗口已过。若无线"
                                   f"仍未恢复，请走近设备用物理开关或插网线管理。")
            return
        self.wifi_hint.setText(f"已挂 {wifi.ROLLBACK_DELAY} 秒自动恢复：{left} "
                              f"秒后路由器自动 wifi up。期间可点「取消自动恢复」。")
