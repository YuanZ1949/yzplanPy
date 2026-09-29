"""router_admin.widgets.tabs_clients：在线终端 Tab（ARP + dnsmasq 租约合并）。

采集只读两条命令，**真机实测小米固件的租约路径是 `/tmp/dhcp.leases`**（`/tmp/dnsmasq.leases`
与 `/var/etc/dnsmasq.leases` 均为 0 字节）。租约文件不存在时 `run_batch` 会把失败的
那条留成空串、`parse_dnsmasq_leases` 返回 []，**不报错**，只把来源退化为 ARP。
`merge_clients` 已过滤 `flags & 0x2 == 0` 的 incomplete（占位未应答 = 离线）条目。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label

from .. import parsers
from . import notify
from .tables import fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

#: 只读采集命令（顺序即解析下标）
#: 第二条必须是 `/tmp/dhcp.leases`——本机小米固件实测该路径才有内容。
CLIENT_COMMANDS = ("cat /proc/net/arp", "cat /tmp/dhcp.leases")
_C_ARP, _C_LEASES = range(2)

_HEADERS = ("IP 地址", "MAC 地址", "主机名", "接口", "来源")
_COLS = (("ip", None), ("mac", None), ("hostname", None), ("dev", None),
         ("source", None))
_EMPTY = "—"


def collect_clients(session):
    """后台采集：返回 [{ip, mac, hostname, dev, source}]，source ∈ {DHCP, ARP}。"""
    out = session.run_batch(CLIENT_COMMANDS)
    arp = parsers.parse_arp(out[_C_ARP])
    leases = parsers.parse_dnsmasq_leases(out[_C_LEASES])
    dhcp_ips = {item.get("ip") for item in leases if item.get("ip")}
    rows = []
    for item in parsers.merge_clients(arp, leases):
        rows.append({
            "ip": item.get("ip") or _EMPTY,
            "mac": item.get("mac") or _EMPTY,
            "hostname": item.get("hostname") or _EMPTY,
            "dev": item.get("dev") or _EMPTY,
            "source": "DHCP" if item.get("ip") in dhcp_ips else "ARP",
        })
    rows.sort(key=lambda r: _ip_key(r["ip"]))
    return {"rows": rows, "leases": len(leases), "arp": len(arp)}


def _ip_key(text):
    parts = str(text).split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return (999, 999, 999, 999)


class ClientsTab(QtWidgets.QWidget):
    """在线终端页。"""

    def __init__(self, owner, group, *, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sizing()["dialog_spacing"])
        head = QtWidgets.QHBoxLayout()
        self.summary = make_label("尚未采集", role="subtitle", parent=self)
        head.addWidget(self.summary)
        head.addStretch(1)
        self.btn_refresh = make_button("手动刷新", size="sm", parent=self)
        self.btn_refresh.clicked.connect(lambda: self.refresh())
        head.addWidget(self.btn_refresh)
        lay.addLayout(head)
        self.table = make_table(_HEADERS, parent=self,
                                min_height=sizing()["log_table_min_height"])
        lay.addWidget(self.table, 1)
        self.hint = make_label(
            "只统计 ARP 中 flags 完整（在线）的条目；incomplete 占位已过滤。",
            role="caption", parent=self)
        lay.addWidget(self.hint)

    def refresh(self):
        if not self._group.start(collect_clients, on_ok=self.apply_result,
                                 on_err=self._on_error, label="collect_clients"):
            notify(self, "无法刷新", "尚未连接路由器或上一轮采集未结束。",
                   error=True)
            return False
        self.summary.setText("采集中…")
        return True

    def _on_error(self, kind, text):
        self.summary.setText("采集失败")
        notify(self, "在线终端采集失败", text, error=True)

    def apply_result(self, data):
        rows = data.get("rows") or []
        fill_table(self.table, rows, _COLS, chips={
            4: lambda r: (r["source"],
                          "success" if r["source"] == "DHCP" else "info")})
        self.summary.setText(f"共 {len(rows)} 个在线终端")
        if not data.get("leases"):
            self.hint.setText(
                "未读到 dnsmasq 租约（/tmp/dhcp.leases 不存在或为空），"
                "主机名列显示为「—」，来源全部标记为 ARP。")
        else:
            self.hint.setText(
                f"合并了 {data.get('arp', 0)} 条 ARP 与 {data['leases']} 条 DHCP 租约；"
                "incomplete 占位已过滤。")
