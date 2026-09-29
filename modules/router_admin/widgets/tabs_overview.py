"""router_admin.widgets.tabs_overview：总览 Tab（状态卡 / 内存 / 磁盘 / 网速 / 进程）。

8 条只读命令在**一个** TelnetSession 里 `run_batch` 一次拿完。网速与 CPU 都靠
「两次采样差值」，基线存在 `Module` 实例上（`prev_net_dev` / `prev_net_ts` /
`prev_proc_stat`）。**首次采样没有基线**，一律显示「—」而不是 0。
"""
import time
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_label

from .. import parsers
from ..connection import format_bytes
from . import make_card_block, make_stat_card, make_usage_bar
from .tables import fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

#: 一次 batch 取完的只读命令（顺序即解析下标；单条须远短于 tty 行缓冲上限）
OVERVIEW_COMMANDS = (
    "cat /proc/uptime", "cat /proc/meminfo", "cat /proc/stat", "cat /proc/net/dev",
    "ifconfig -a", "cat /proc/net/arp", "ps", "df -k",
)
_C_UP, _C_MEM, _C_STAT, _C_NET, _C_IF, _C_ARP, _C_PS, _C_DF = range(8)
TOP_N, _NO = 10, "—"
_SKIP_IFACES = frozenset({"lo"})          # 回环接口的流量无意义
_CARDS = (("wan", "WAN IP"), ("ipv6", "IPv6"), ("uptime", "运行时长"),
          ("clients", "在线终端"), ("procs", "进程数"), ("cpu", "CPU 占用"))
_DF_HEADERS = ("挂载点", "已用", "可用", "使用率")
_DF_COLS = (("mount", None), ("used", None), ("avail", None), ("pct", None))
_NET_HEADERS = ("接口", "下行 KB/s", "上行 KB/s", "累计接收", "累计发送")
_NET_COLS = (("iface", None), ("rx", None), ("tx", None),
             ("rx_total", None), ("tx_total", None))
_PROC_HEADERS = ("PID", "进程", "CPU 时间(累计)")
_PROC_COLS = (("pid", None), ("comm", None), ("extra", None))
#: 进程第 3 列在不同固件上的列头（真机 BusyBox ps 无 TIME 列，见 _proc_extra）
_PROC_TIME_HDR, _PROC_VSZ_HDR, _PROC_NONE_HDR = "CPU 时间(累计)", "虚拟内存 VSZ", "附加信息"


def _plain_rank(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return -1.0

def _time_rank(text):
    """BusyBox TIME（`mm:ss` / `HH:MM:SS` / 纯数字秒）→ 可排序的秒数。"""
    try:
        return sum(float(x) * (60 ** i)
                   for i, x in enumerate(reversed(str(text or "").split(":"))))
    except ValueError:
        return -1.0


def _ps_column(text, name):
    """`ps` 原始文本 → ({pid: 该列文本}, 列下标)；列不存在时下标为 -1。"""
    rows, idx = {}, -1
    for line in (text or "").splitlines():
        f = line.split()
        if f and f[0].upper() == "PID":
            head = [c.upper() for c in f]
            idx = head.index(name) if name in head else -1
        elif idx >= 0 and len(f) > idx:
            try:
                rows[int(f[0])] = f[idx]
            except ValueError:
                pass
    return rows, idx

def _proc_extra(text):
    """挑一个 ps 里**真实存在**的可排序列 → ({pid: 值}, 列头, 排序函数)。

    真机（小米小胖 / BusyBox v1.25.1）表头是 `PID USER VSZ STAT COMMAND`——既无
    TIME 列也无 %CPU。故优先 TIME、拿不到退 VSZ 并如实改列头，绝不编造 CPU 时间。
    """
    for name, label, rank in (("TIME", _PROC_TIME_HDR, _time_rank),
                              ("VSZ", _PROC_VSZ_HDR, _plain_rank)):
        rows, idx = _ps_column(text, name)
        if idx >= 0:
            return rows, label, rank
    return {}, _PROC_NONE_HDR, _plain_rank

def _iface(rows, name):
    return next((row for row in rows or [] if row.get("iface") == name), {})

def _iface_speeds(prev, cur, gap):
    """两次 /proc/net/dev 差值 → {iface: (下行 KB/s, 上行 KB/s)}；无基线返回 {}。"""
    if not prev or not cur or not gap:
        return {}
    old = {row["iface"]: row for row in prev}
    out = {}
    for row in cur:
        before = old.get(row["iface"])
        if before is not None:
            out[row["iface"]] = (
                max(0, row["rx_bytes"] - before["rx_bytes"]) / gap / 1024.0,
                max(0, row["tx_bytes"] - before["tx_bytes"]) / gap / 1024.0)
    return out

def collect_overview(session, *, prev_net_dev=None, prev_proc_stat=None,
                     prev_net_ts=None):
    """后台采集一轮总览，返回纯数据 dict（含下一轮差值所需的基线）。"""
    out = session.run_batch(OVERVIEW_COMMANDS)
    cpu = parsers.parse_proc_stat(out[_C_STAT], prev_proc_stat)
    net = parsers.parse_net_dev(out[_C_NET])
    now = time.monotonic()
    return {
        "uptime_s": (parsers.parse_uptime(out[_C_UP]) or {}).get("uptime_s"),
        "mem": parsers.parse_meminfo(out[_C_MEM]),
        "cpu_pct": (cpu or {}).get("cpu_pct"),
        "ifaces": parsers.parse_ifconfig(out[_C_IF]),
        "net_rows": net, "arp": parsers.parse_arp(out[_C_ARP]),
        "ps": parsers.parse_ps(out[_C_PS]), "ps_text": out[_C_PS],
        "df": parsers.parse_df(out[_C_DF]),
        "speeds": _iface_speeds(prev_net_dev, net,
                                (now - prev_net_ts) if prev_net_ts else None),
        "baseline": {"net_dev": net, "net_ts": now, "proc_stat": cpu},
    }

class OverviewTab(QtWidgets.QWidget):
    """总览页。`refresh()` 发采集，`apply_result()` 在主线程渲染。"""
    def __init__(self, owner, group, *, parent=None):
        super().__init__(parent)
        self._owner, self._group, self._cards = owner, group, {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sizing()["dialog_spacing"])
        lay.addWidget(self._build_cards())
        lay.addWidget(self._build_mem())
        lay.addLayout(self._build_tables())
        self.status = make_label("", role="caption", parent=self)
        lay.addWidget(self.status)

    def _build_cards(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["dialog_spacing"])
        for key, title in _CARDS:
            card, value = make_stat_card(title, parent=self)
            self._cards[key] = value
            row.addWidget(card, 1)
        wrap = QtWidgets.QWidget(self)
        wrap.setLayout(row)
        return wrap

    def _build_mem(self):
        card, lay = make_card_block("内存", parent=self)
        head = QtWidgets.QHBoxLayout()
        head.addStretch(1)
        self.mem_detail = make_label(_NO, role="caption", parent=card)
        head.addWidget(self.mem_detail)
        lay.addLayout(head)
        self.mem_bar = make_usage_bar(parent=card)
        lay.addWidget(self.mem_bar)
        return card

    def _build_tables(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["dialog_spacing"])
        self.df_table = make_table(_DF_HEADERS, parent=self)
        self.net_table = make_table(_NET_HEADERS, parent=self)
        self.proc_table = make_table(_PROC_HEADERS, parent=self)
        for table, title in ((self.df_table, "磁盘占用"), (self.net_table, "实时网速"),
                             (self.proc_table, f"进程 Top {TOP_N}")):
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(sizing()["radius_xs"])
            box.addWidget(make_label(title, role="caption", parent=self))
            box.addWidget(table, 1)
            row.addLayout(box, 1)
        return row

    def refresh(self):
        """发起后台采集。基线在主线程读（同一时刻只有一个任务在跑，无竞态）。"""
        o = self._owner
        return self._group.start(
            lambda s: collect_overview(
                s, prev_net_dev=o.prev_net_dev, prev_proc_stat=o.prev_proc_stat,
                prev_net_ts=o.prev_net_ts),
            on_ok=self.apply_result, label="collect_overview")

    def apply_result(self, data):
        """写卡片/内存条/三张表，并把新基线存回 Module 实例（主线程）。"""
        base = data.get("baseline") or {}
        self._owner.prev_net_dev = base.get("net_dev")
        self._owner.prev_proc_stat = base.get("proc_stat")
        self._owner.prev_net_ts = base.get("net_ts")
        ifaces = data.get("ifaces") or []
        wan = _iface(ifaces, self._owner.wan_iface)
        self._owner.lan_ip = _iface(ifaces, self._owner.lan_iface).get("inet")
        clients = sum(1 for row in data.get("arp") or [] if row.get("complete"))
        cpu = data.get("cpu_pct")
        cards = (("wan", wan.get("inet") or _NO), ("ipv6", wan.get("inet6") or _NO),
                 ("uptime", parsers.parse_uptime_fmt(data.get("uptime_s"))),
                 ("clients", str(clients)),
                 ("procs", str((data.get("ps") or {}).get("count", 0))),
                 ("cpu", _NO if cpu is None else f"{cpu:.1f}%"))
        for key, value in cards:
            self._cards[key].setText(value)
        self._apply_mem(data.get("mem"))
        self._apply_df(data.get("df"))
        self._apply_net(data)
        self._apply_procs(data.get("ps"), data.get("ps_text"))
        self._owner.snapshot = {"online": True, "tried": True,
                                "wan_ip": wan.get("inet") or _NO,
                                "uptime_s": data.get("uptime_s"), "clients": clients}
        self.status.setText(
            f"WAN {self._owner.wan_iface} · LAN {self._owner.lan_ip or _NO} · "
            f"ARP {len(data.get('arp') or [])} 条（在线 {clients}）")

    def _apply_mem(self, mem):
        if not mem:
            self.mem_detail.setText(_NO)
            self.mem_bar.set_percent(0, _NO)
            return
        kb = lambda k: format_bytes(k * 1024)          # noqa: E731 - 局部短别名
        self.mem_detail.setText(
            f"总计 {kb(mem['total_kb'])} · 可用 {kb(mem['available_kb'])} · "
            f"空闲 {kb(mem['free_kb'])} · 缓存 {kb(mem['cached_kb'])}")
        self.mem_bar.set_percent(mem["used_pct"], f"{mem['used_pct']:.1f}%")

    def _apply_df(self, rows):
        out = [{"mount": r.get("mount"),
                "used": format_bytes(r.get("used_kb", 0) * 1024),
                "avail": format_bytes(r.get("avail_kb", 0) * 1024),
                "pct": f"{r.get('use_pct', 0)}%",
                "hi": r.get("use_pct", 0) >= 90} for r in rows or []]
        fill_table(self.df_table, out, _DF_COLS,
                   chips={3: lambda r: (r["pct"], "error" if r["hi"] else "info")})

    def _apply_net(self, data):
        speeds = data.get("speeds") or {}
        out = []
        for row in data.get("net_rows") or []:
            if row.get("iface") in _SKIP_IFACES:
                continue
            rx, tx = speeds.get(row.get("iface"), (None, None))
            out.append({"iface": row.get("iface"),
                        "rx": _NO if rx is None else f"{rx:.1f}",
                        "tx": _NO if tx is None else f"{tx:.1f}",
                        "rx_total": format_bytes(row.get("rx_bytes", 0)),
                        "tx_total": format_bytes(row.get("tx_bytes", 0))})
        fill_table(self.net_table, out, _NET_COLS, numeric={1, 2, 3, 4})

    def _apply_procs(self, ps, ps_text):
        values, label, rank = _proc_extra(ps_text)
        self.proc_table.setHorizontalHeaderItem(2, QtWidgets.QTableWidgetItem(label))
        rows = [{"pid": p["pid"], "comm": p["comm"], "extra": values.get(p["pid"], _NO)}
                for p in (ps or {}).get("procs", [])]
        rows.sort(key=lambda r: rank(r["extra"]), reverse=True)
        fill_table(self.proc_table, rows[:TOP_N], _PROC_COLS, numeric={0})
