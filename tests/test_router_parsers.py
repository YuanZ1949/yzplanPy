"""router_admin 解析层测试：纯函数 + 真机探测样本，全部离线（不连任何地址）。

样本来自 2026-09-29 对 192.168.2.1（小胖 / BusyBox v1.25.1）的只读探测，
本文件不建立任何网络连接。
"""
import pytest

from modules.router_admin import parsers as p

UPTIME = "33194.93 15012345.67\n"

MEMINFO = """\
MemTotal:       182868 kB
MemFree:         27816 kB
MemAvailable:    27500 kB
Buffers:          2048 kB
Cached:          35656 kB
Slab:            64704 kB
SwapTotal:             0 kB
SwapFree:              0 kB
"""

# 老内核（无 MemAvailable）
MEMINFO_OLD = """\
MemTotal:       182868 kB
MemFree:         27816 kB
Buffers:          2048 kB
Cached:          35656 kB
Slab:            64704 kB
"""

LOADAVG = "0.42 0.35 0.30 2/231 5678\n"

STAT_A = ("cpu  1234567 8901 456789 9876543 12345 0 1234 0 0 0\n"
          "cpu0  617283 4450 228394 4938271 6172 0 617 0 0 0\n"
          "intr 12345678\n")
STAT_B = ("cpu  1235567 9001 456889 9877043 12345 0 1234 0 0 0\n"
          "cpu0  617883 4600 228544 4938621 6172 0 617 0 0 0\n"
          "intr 12345690\n")

NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  1234567    8901    0    0    0     0          0         0  1234567    8901    0    0    0     0       0          0
  eth0: 27150000000  12345678   12     3    0     0          0         0  8100000000  4567890    0    0    0     0       0          0
   wl0: 8750000000   3456789    0    0    0     0          0         0  1230000000  2345678    1    0    0     0       0          0
br-lan: 8750000000   3456789    0    0    0     0          0         0  1230000000  2345678    0    0    0     0       0          0
"""

IFCONFIG = """\
br-lan    Link encap:Ethernet  HWaddr 5C:02:14:F4:7E:86
          inet addr:192.168.2.1  Bcast:192.168.2.255  Mask:255.255.255.0
          inet6 addr: fe80::5e02:14ff:feF4:7E86/64 Scope: Link
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1
          RX packets:12345678 errors:12 dropped:3 overruns:0 frame:0
pppoe-wan Link encap:POINTOPOINT  HWaddr 5C:02:14:44:8E:B6
          inet addr:100.64.159.39  P-t-P:100.64.159.1  Mask:255.255.255.255
          UP POINTOPOINT RUNNING NOARP MULTICAST  MTU:1480  Metric:1
wl0       Link encap:Ethernet  HWaddr 5C:02:14:F4:7E:87
          inet6 addr: fe80::5e02:14ff:feF4:7E87/64 Scope: Link
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1
lo        Link encap:Local Loopback
          inet addr:127.0.0.1  Mask:255.0.0.0
          UP LOOPBACK RUNNING  MTU:65536  Metric:1
"""

ARP = """\
IP address       HW type     Flags       HW address            Mask     Device
192.168.2.100    0x1         0x2         aa:bb:cc:dd:ee:ff     *        br-lan
192.168.2.101    0x1         0x0         00:00:00:00:00:00     *        br-lan
192.168.32.50    0x1         0x2         11:22:33:44:55:66     *        br-miot
"""

# 任务书给定的列序：<mac> <ip> <hostname> <expiry> <name>
LEASES = """\
5c:02:14:f4:7e:10 192.168.2.100 laptop-pc 1750000000 laptop-pc
5c:02:14:f4:7e:11 192.168.2.101 * 1750000000 *
"""

# 真实 dnsmasq 租约列序：<expiry> <mac> <ip> <hostname> <client-id>
LEASES_STD = "1750000000 5c:02:14:f4:7e:10 192.168.2.100 laptop-pc 01:aa:bb:cc\n"

PS = """\
  PID USER     TIME  COMMAND
    1 root      0:00 init
  567 root      0:00 /sbin/udhcpc -i br-lan
 1234 root      0:05 /usr/sbin/hostapd /var/run/hostapd -P /var/run/wpa
 2345 root      0:00 telnetd
"""

DF = """\
Filesystem           1K-blocks      Used Available Use% Mounted on
/dev/root                43008     24576     17664  58% /
tmpfs                    15360        0     15360   0% /tmp
/dev/mtdblock7
                 102400     20480     81920  20% /overlay
"""


# ── parse_uptime ────────────────────────────────────────────────

def test_uptime_带小数秒():
    assert p.parse_uptime(UPTIME) == {"uptime_s": 33194.93}


def test_uptime_忽略第二列():
    assert p.parse_uptime("123 456\n") == {"uptime_s": 123.0}


@pytest.mark.parametrize("bad", ["", "   ", None, "abc", "cat: no such file"])
def test_uptime_异常输入返回None(bad):
    assert p.parse_uptime(bad) is None


# ── parse_meminfo ───────────────────────────────────────────────

def test_meminfo_字段齐全():
    r = p.parse_meminfo(MEMINFO)
    assert r == {
        "total_kb": 182868, "free_kb": 27816, "available_kb": 27500,
        "cached_kb": 35656, "slab_kb": 64704, "used_pct": 85.0,
    }


def test_meminfo_缺MemAvailable回落Free加Buffers加Cached():
    r = p.parse_meminfo(MEMINFO_OLD)
    assert r["available_kb"] == 27816 + 2048 + 35656
    assert r["used_pct"] == round(100 * (182868 - 65520) / 182868, 1)


def test_meminfo_无MemTotal返回None():
    assert p.parse_meminfo("MemFree: 100 kB\n") is None


@pytest.mark.parametrize("bad", ["", None, "cat: can't open '/proc/meminfo'"])
def test_meminfo_异常输入返回None(bad):
    assert p.parse_meminfo(bad) is None


# ── parse_proc_stat ─────────────────────────────────────────────
#
# 契约（2026-09-29 真机修复后）：只有 `text` 里没有可解析的 `cpu` 聚合行才返回
# None；「无可用历史」的首调 / Δtotal ≤ 0 一律返回**基线字典**
# `{"cpu_pct": None, "total": int, "idle": int}`，供调用方存下来当下一轮的 `prev`。
# 老实现在这两种情况下返回 None，调用方手里没有任何东西可存，CPU 占用率永远是「—」。

def test_proc_stat_首调无历史返回jiffies基线():
    r = p.parse_proc_stat(STAT_A, None)
    assert r == {"cpu_pct": None, "total": 11590379, "idle": 9888888}


def test_proc_stat_基线可当下一轮prev用():
    first = p.parse_proc_stat(STAT_A, None)
    assert p.parse_proc_stat(STAT_B, first) == {"cpu_pct": 70.6}


def test_proc_stat_两次采样算占用率():
    # Δtotal=1700，Δidle=500 → 100*(1-500/1700)=70.6
    assert p.parse_proc_stat(STAT_B, STAT_A) == {"cpu_pct": 70.6}


def test_proc_stat_只取聚合行不算cpu0():
    # cpu0 单独算会得到 72.0，与聚合行 70.6 不同
    assert p.parse_proc_stat(STAT_B, STAT_A)["cpu_pct"] != 72.0


def test_proc_stat_总差为0返回基线():
    r = p.parse_proc_stat(STAT_A, STAT_A)
    assert r["cpu_pct"] is None
    assert r["total"] == 11590379


def test_proc_stat_总差为负返回基线():
    r = p.parse_proc_stat(STAT_A, STAT_B)
    assert r["cpu_pct"] is None
    assert r["total"] == 11590379


def test_proc_stat_接受prev为已解析字典():
    prev = {"total": 11590379, "idle": 9888888}
    assert p.parse_proc_stat(STAT_B, prev) == {"cpu_pct": 70.6}


def test_proc_stat_缺total的字典不抛KeyError():
    # 只有 cpu_pct 的历史结果没有 jiffies，须优雅降级为基线而不是抛 KeyError
    r = p.parse_proc_stat(STAT_B, {"cpu_pct": 12.3})
    assert r == {"cpu_pct": None, "total": 11592079, "idle": 9889388}


@pytest.mark.parametrize("bad", ["", None, "intr 1 2 3", "cpu 1 2"])
def test_proc_stat_文本无cpu聚合行返回None(bad):
    assert p.parse_proc_stat(bad, STAT_A) is None


@pytest.mark.parametrize("bad", ["", None, "intr 1 2 3", "cpu 1 2"])
def test_proc_stat_prev不可用时返回基线而非None(bad):
    r = p.parse_proc_stat(STAT_A, bad)
    assert r == {"cpu_pct": None, "total": 11590379, "idle": 9888888}


# ── parse_loadavg ───────────────────────────────────────────────

def test_loadavg_三档():
    assert p.parse_loadavg(LOADAVG) == {"load1": 0.42, "load5": 0.35, "load15": 0.30}


@pytest.mark.parametrize("bad", ["", None, "0.42 0.35", "a b c", "sh: loadavg: not found"])
def test_loadavg_异常输入返回None(bad):
    assert p.parse_loadavg(bad) is None


# ── parse_net_dev ───────────────────────────────────────────────

def test_net_dev_四个接口():
    rows = {r["iface"]: r for r in p.parse_net_dev(NET_DEV)}
    assert set(rows) == {"lo", "eth0", "wl0", "br-lan"}


def test_net_dev_接口名带冒号被正确切分():
    rows = {r["iface"]: r for r in p.parse_net_dev(NET_DEV)}
    assert rows["eth0"] == {
        "iface": "eth0", "rx_bytes": 27150000000, "tx_bytes": 8100000000,
        "rx_pkt": 12345678, "tx_pkt": 4567890, "errs": 12, "drop": 3,
    }


def test_net_dev_保留lo交由调用方过滤():
    rows = {r["iface"]: r for r in p.parse_net_dev(NET_DEV)}
    assert rows["lo"]["rx_bytes"] == 1234567
    assert rows["wl0"]["errs"] == 0
    assert rows["br-lan"]["tx_bytes"] == 1230000000


def test_net_dev_跳过表头():
    assert all(r["iface"] not in ("face", "Inter-") for r in p.parse_net_dev(NET_DEV))


@pytest.mark.parametrize("bad", ["", None, "cat: no such file", "eth0: 1 2 3"])
def test_net_dev_异常输入返回空列表(bad):
    assert p.parse_net_dev(bad) == []


# ── parse_ifconfig ──────────────────────────────────────────────

def test_ifconfig_三张网卡():
    rows = {r["iface"]: r for r in p.parse_ifconfig(IFCONFIG)}
    assert set(rows) == {"br-lan", "pppoe-wan", "wl0", "lo"}


def test_ifconfig_br_lan字段():
    rows = {r["iface"]: r for r in p.parse_ifconfig(IFCONFIG)}
    b = rows["br-lan"]
    assert b["inet"] == "192.168.2.1"
    assert b["netmask"] == "255.255.255.0"
    assert b["mac"] == "5C:02:14:F4:7E:86"
    assert b["mtu"] == 1500
    assert b["hwaddr_hwtype"] == "Ethernet"


def test_ifconfig_wan为CGNAT地址():
    rows = {r["iface"]: r for r in p.parse_ifconfig(IFCONFIG)}
    w = rows["pppoe-wan"]
    assert w["inet"] == "100.64.159.39"
    assert w["netmask"] == "255.255.255.255"
    assert w["mtu"] == 1480


def test_ifconfig_无inet的网卡也收录():
    rows = {r["iface"]: r for r in p.parse_ifconfig(IFCONFIG)}
    assert rows["wl0"]["inet"] is None
    assert rows["wl0"]["mac"] == "5C:02:14:F4:7E:87"


def test_ifconfig_不把inet6当ipv4():
    rows = {r["iface"]: r for r in p.parse_ifconfig(IFCONFIG)}
    assert rows["br-lan"]["inet"] == "192.168.2.1"
    assert "::" not in str(rows["br-lan"]["inet"])


@pytest.mark.parametrize("bad", ["", None, "ifconfig: not found"])
def test_ifconfig_异常输入返回空列表(bad):
    assert p.parse_ifconfig(bad) == []


# ── parse_arp ───────────────────────────────────────────────────

def test_arp_三行():
    rows = {r["ip"]: r for r in p.parse_arp(ARP)}
    assert rows["192.168.2.100"] == {
        "ip": "192.168.2.100", "mac": "aa:bb:cc:dd:ee:ff",
        "dev": "br-lan", "complete": True,
    }
    assert rows["192.168.32.50"]["dev"] == "br-miot"


def test_arp_flags为0判不完整():
    rows = {r["ip"]: r for r in p.parse_arp(ARP)}
    assert rows["192.168.2.101"]["complete"] is False
    assert rows["192.168.2.101"]["mac"] == "00:00:00:00:00:00"


def test_arp_跳过表头():
    assert all("IP" != r["ip"] for r in p.parse_arp(ARP))


@pytest.mark.parametrize("bad", ["", None, "cat: no such file"])
def test_arp_异常输入返回空列表(bad):
    assert p.parse_arp(bad) == []


# ── parse_dnsmasq_leases ────────────────────────────────────────

def test_leases_按任务书列序解析():
    rows = {r["ip"]: r for r in p.parse_dnsmasq_leases(LEASES)}
    assert rows["192.168.2.100"] == {
        "mac": "5c:02:14:f4:7e:10", "ip": "192.168.2.100",
        "hostname": "laptop-pc", "expires": 1750000000,
    }


def test_leases_通配主机名转None():
    rows = {r["ip"]: r for r in p.parse_dnsmasq_leases(LEASES)}
    assert rows["192.168.2.101"]["hostname"] is None


def test_leases_兼容标准dnsmasq列序():
    assert p.parse_dnsmasq_leases(LEASES_STD) == [
        {"mac": "5c:02:14:f4:7e:10", "ip": "192.168.2.100",
         "hostname": "laptop-pc", "expires": 1750000000},
    ]


@pytest.mark.parametrize("bad", ["", None, "cat: can't open '/tmp/dnsmasq.leases'"])
def test_leases_缺失文件返回空列表(bad):
    assert p.parse_dnsmasq_leases(bad) == []


# ── parse_ps ────────────────────────────────────────────────────

def test_ps_进程数与字段():
    r = p.parse_ps(PS)
    assert r["count"] == 4
    assert r["procs"][0] == {"pid": 1, "comm": "init", "args": "init"}


def test_ps_长命令行不按空白截断():
    r = p.parse_ps(PS)
    assert r["procs"][2]["args"] == (
        "/usr/sbin/hostapd /var/run/hostapd -P /var/run/wpa")
    assert r["procs"][2]["comm"] == "hostapd"
    assert r["procs"][1]["pid"] == 567


def test_ps_不假设存在CPU列():
    # 样本里没有 %CPU / VSZ 列，解析不得因此失败
    assert p.parse_ps(PS)["count"] == 4


@pytest.mark.parametrize("bad", ["", None, "ps: not found", "no header here"])
def test_ps_异常输入返回None(bad):
    assert p.parse_ps(bad) is None


# ── parse_df ────────────────────────────────────────────────────

def test_df_两行正常记录():
    rows = {r["mount"]: r for r in p.parse_df(DF)}
    assert rows["/"] == {
        "mount": "/", "total_kb": 43008, "used_kb": 24576,
        "avail_kb": 17664, "use_pct": 58,
    }
    assert rows["/tmp"]["use_pct"] == 0


def test_df_行尾折行仍能归并():
    rows = {r["mount"]: r for r in p.parse_df(DF)}
    assert rows["/overlay"] == {
        "mount": "/overlay", "total_kb": 102400, "used_kb": 20480,
        "avail_kb": 81920, "use_pct": 20,
    }


def test_df_挂载点折到下一行也能归并():
    text = ("Filesystem           1K-blocks      Used Available Use% Mounted on\n"
            "/dev/root                43008     24576     17664  58%\n"
            "/overlay\n")
    rows = {r["mount"]: r for r in p.parse_df(text)}
    assert rows["/overlay"] == {
        "mount": "/overlay", "total_kb": 43008, "used_kb": 24576,
        "avail_kb": 17664, "use_pct": 58,
    }


@pytest.mark.parametrize("bad", ["", None, "df: not found"])
def test_df_异常输入返回空列表(bad):
    assert p.parse_df(bad) == []


# ── parse_uptime_fmt ────────────────────────────────────────────

def test_uptime_fmt_天级():
    assert p.parse_uptime_fmt(3 * 86400 + 4 * 3600 + 5 * 60) == "3 天 4 时 5 分"


def test_uptime_fmt_时级():
    assert p.parse_uptime_fmt(4 * 3600 + 5 * 60) == "4 时 5 分"


def test_uptime_fmt_分级():
    assert p.parse_uptime_fmt(5 * 60) == "5 分"


def test_uptime_fmt_天数为0时补0():
    assert p.parse_uptime_fmt(2 * 86400 + 60) == "2 天 0 时 1 分"


def test_uptime_fmt_不足一分钟():
    assert p.parse_uptime_fmt(59) == "0 分"


@pytest.mark.parametrize("bad", [None, "", "abc", -1])
def test_uptime_fmt_异常输入返回破折号(bad):
    assert p.parse_uptime_fmt(bad) == "—"


# ── merge_clients ───────────────────────────────────────────────

def test_merge_clients_按IP关联并优先主机名():
    arp = p.parse_arp(ARP)
    leases = p.parse_dnsmasq_leases(LEASES)
    rows = {r["ip"]: r for r in p.merge_clients(arp, leases)}
    assert rows["192.168.2.100"]["hostname"] == "laptop-pc"
    assert rows["192.168.2.100"]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert rows["192.168.2.100"]["dev"] == "br-lan"


def test_merge_clients_过滤不完整ARP项():
    rows = p.merge_clients(p.parse_arp(ARP), p.parse_dnsmasq_leases(LEASES))
    assert "192.168.2.101" not in {r["ip"] for r in rows}


def test_merge_clients_无租约项MAC兜底():
    rows = {r["ip"]: r for r in p.merge_clients(p.parse_arp(ARP), [])}
    assert rows["192.168.32.50"] == {
        "ip": "192.168.32.50", "mac": "11:22:33:44:55:66",
        "hostname": None, "dev": "br-miot",
    }


def test_merge_clients_租约主机名为通配符时用None():
    rows = {r["ip"]: r for r in p.merge_clients(
        p.parse_arp(ARP), p.parse_dnsmasq_leases(LEASES))}
    assert rows["192.168.32.50"]["hostname"] is None


@pytest.mark.parametrize("arp,leases", [([], []), (None, None), (None, []), ([], None)])
def test_merge_clients_空输入返回空列表(arp, leases):
    assert p.merge_clients(arp, leases) == []


# ── 纯函数性质 ──────────────────────────────────────────────────

ALL_PARSERS = [
    (p.parse_uptime, UPTIME, None),
    (p.parse_meminfo, MEMINFO, None),
    (p.parse_loadavg, LOADAVG, None),
    (p.parse_net_dev, NET_DEV, []),
    (p.parse_ifconfig, IFCONFIG, []),
    (p.parse_arp, ARP, []),
    (p.parse_dnsmasq_leases, LEASES, []),
    (p.parse_ps, PS, None),
    (p.parse_df, DF, []),
]

BAD_TEXTS = ["", "   \n\n", "cat: can't open file: No such file",
             "\x00\x01\x02", "root@XiaoQiang:~# "]


@pytest.mark.parametrize("fn,sample,expected", ALL_PARSERS)
def test_各解析器对异常文本不抛异常且返回降级值(fn, sample, expected):
    assert fn(sample) not in (None, expected)  # 样本本身应解析出内容
    for bad in BAD_TEXTS:
        assert fn(bad) == expected
