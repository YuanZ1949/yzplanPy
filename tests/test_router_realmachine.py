"""router_admin 解析层**真机样本**回归测试（2026-09-29 小胖 / 192.168.2.1）。

与 `test_router_parsers.py` 的区别：那里的样本是**合成**的（`PID USER TIME
COMMAND` 表头、无 ANSI 色码、`/proc/stat` 单空格），与本机 BusyBox v1.25.1 的真实
输出有系统性差异 —— 5 个解析 bug 全部由这种差异引起。本文件逐条锁定真机形态。

样本均为**真机只读命令的原始输出**（`cat /proc/stat` / `ps` / `ls -1 /etc/init.d`
/ `ifconfig`），已按原样保留：
- `/proc/stat` 聚合行 `cpu` 与首个数字之间是**两个空格**；
- `ps` 表头是 `PID USER VSZ STAT COMMAND`（**没有 TIME 列**），STAT 带优先级字符
  （`SW<`），内核线程 COMMAND 是方括号包裹且**含斜杠**（`[ksoftirqd/0]`），
  用户进程命令行**含空格**；
- `ls -1` 的 BusyBox 开了 **ANSI 颜色**（行首 `\\x1b[1;32m`、行尾 `\\x1b[0m`），
  且输出以一个换行符开头；
- `wl0`/`wl1` 已被 enslaved 到 `br-lan`，**自身不持有 IPv4**。

全部离线（不建立任何网络连接），纯逻辑层不 import Qt。
"""
import pytest

from modules.router_admin import parsers as p
from modules.router_admin import services, wifi

# ── 真机样本 ─────────────────────────────────────────────────────────

#: `cat /proc/stat`：聚合行与 cpu0/cpu1 之间，`cpu` 后是**两个空格**
REAL_PROC_STAT = (
    "cpu  634498 0 450397 9247763 203 0 568571 0 0 0\n"
    "cpu0 317249 0 225198 4623881 101 0 284285 0 0 0\n"
    "cpu1 317249 0 225199 4623882 102 0 284286 0 0 0\n"
    "intr 120700783 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
    "ctxt 38948706\n"
    "btime 1790586230\n"
    "processes 993106\n"
    "procs_running 1\n"
    "procs_blocked 0\n"
    "softirq 137431935 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
)

#: 同一台机器的**稍后**一次采样：user +100、idle +50 → 100*(1-50/150) = 66.7%
REAL_PROC_STAT_LATER = (
    "cpu  634598 0 450397 9247813 203 0 568571 0 0 0\n"
    "cpu0 317299 0 225198 4623931 101 0 284285 0 0 0\n"
    "cpu1 317299 0 225199 4623932 102 0 284286 0 0 0\n"
    "intr 120700900 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
)

#: `ps`：真机表头是 `PID USER VSZ STAT COMMAND`（**无 TIME 列**）
REAL_PS = """\
  PID USER       VSZ STAT COMMAND
    1 root      1520 S    /sbin/procd
    2 root         0 SW   [kthreadd]
    3 root         0 SW   [ksoftirqd/0]
    5 root         0 SW<  [kworker/0:0H]
    8 root         0 SW   [migration/0]
    9 root         0 SW   [rcu_sched]
   11 root         0 SW   [ksoftirqd/1]
   13 root         0 SW   [migration/1]
   14 root         0 SW   [rcu_bh]
   15 root         0 SW   [kworker/1:0H]
   16 root         0 SW   [kworker/0:1H]
   18 root         0 SW   [devfreq_wq]
   19 root         0 SW   [khugepaged]
  275 root      3092 S    /sbin/ubusd
  697 root      3344 S    /usr/sbin/rpcd -t 30
  742 root      4928 S    hostapd -g /var/run/hostapd/global -B -P /var/run/hostapd
 2552 root      3384 S    /usr/sbin/hostapd_cli -i wl1 -p /var/run/hostapd-wif
"""

#: `ls -1 /etc/init.d`：本机 BusyBox 的 ls **开了 ANSI 颜色**，且输出以换行符开头
REAL_LS_INITD = (
    "\n"
    "\x1b[1;32mauto_speedtest\x1b[0m\n"
    "\x1b[1;32mautovpn\x1b[0m\n"
    "\x1b[1;32mboot\x1b[0m\n"
    "\x1b[1;32mboot_check\x1b[0m\n"
    "\x1b[1;32mcab_meshd\x1b[0m\n"
    "\x1b[1;32mcgroup_init\x1b[0m\n"
    "\x1b[1;32mmessagingagent.sh\x1b[0m\n"
    "\x1b[1;32mqca-hostapd\x1b[0m\n"
    "\x1b[1;32mqca-nss-drv\x1b[0m\n"
    "\x1b[1;32msyslog-ng\x1b[0m\n"
)

#: `ifconfig wl0` / `ifconfig wl1`：已被 enslaved 到 br-lan，**自身无 IPv4**
REAL_IFCONFIG_WL = """\
wl0       Link encap:Ethernet  HWaddr 5C:02:14:F4:7E:87
          inet6 addr: fe80::5e02:14ff:fef4:7e87/64 Scope:Link
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1

wl1       Link encap:Ethernet  HWaddr 5C:02:14:F4:7E:88
          inet6 addr: fe80::5e02:14ff:fef4:7e88/64 Scope:Link
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1
"""

#: `ifconfig br-lan`：IPv4 地址在**网桥**上，不在 wlan 接口上
REAL_IFCONFIG_BR = """\
br-lan    Link encap:Ethernet  HWaddr 5C:02:14:F4:7E:86
          inet addr:192.168.2.1  Bcast:192.168.2.255  Mask:255.255.255.0
          inet6 addr: 240e:3b9:34c4:49a0::1/64 Scope:Global
          UP BROADCAST RUNNING MULTICAST  MTU:1500  Metric:1
"""

#: `ps | grep hostapd | grep -v grep` 的真机输出
REAL_PS_HOSTAPD = """\
  742 root      4928 S    hostapd -g /var/run/hostapd/global -B -P /var/run/hostapd
 2552 root      3384 S    /usr/sbin/hostapd_cli -i wl1 -p /var/run/hostapd-wif
"""

# 真机 /proc/stat 聚合行求和：634498+0+450397+9247763+203+0+568571
REAL_TOTAL = 10901432
REAL_IDLE = 9247763 + 203          # idle + iowait


# ── Bug 2: parse_proc_stat 真机（`cpu` 后两个空格 + 首调基线） ─────────

def test_proc_stat_真机双空格聚合行能取出jiffies():
    prev = p.parse_proc_stat(REAL_PROC_STAT, None)
    assert isinstance(prev, dict)
    assert prev["total"] == REAL_TOTAL
    assert prev["idle"] == REAL_IDLE


def test_proc_stat_首调返回可用基线而非None():
    """首调必须给调用方一个能存下来当下次 prev 的字典，否则 CPU 占用率永远是「—」。"""
    prev = p.parse_proc_stat(REAL_PROC_STAT, None)
    assert prev is not None
    assert prev.get("cpu_pct") is None      # 首调没有占用率，但键必须在


def test_proc_stat_基线回传可算出占用率():
    prev = p.parse_proc_stat(REAL_PROC_STAT, None)
    cur = p.parse_proc_stat(REAL_PROC_STAT_LATER, prev)
    assert cur["cpu_pct"] == 66.7          # 100*(1-50/150)


def test_proc_stat_回传上次结果不抛KeyError():
    """prev 是上一次**返回值**时不得抛 KeyError（本模块契约：绝不抛异常）。"""
    first = p.parse_proc_stat(REAL_PROC_STAT, None)
    second = p.parse_proc_stat(REAL_PROC_STAT_LATER, first)
    # 再把「只有 cpu_pct 的结果」当 prev 回传（UI 常见写法），必须优雅降级
    third = p.parse_proc_stat(REAL_PROC_STAT, {"cpu_pct": second["cpu_pct"]})
    assert third is None or third.get("cpu_pct") is None


def test_proc_stat_不接受分核行当聚合行():
    r = p.parse_proc_stat(REAL_PROC_STAT, None)
    # 聚合行 total 是两个分核之和的一半左右（分核 317249 起算）
    assert r["total"] != 317249


# ── Bug 3: parse_ps 真机（VSZ/STAT 表头、内核线程方括号、长命令行） ──

def test_ps_真机表头全部行都解析出来():
    r = p.parse_ps(REAL_PS)
    assert r["count"] == 17
    assert len(r["procs"]) == 17


def test_ps_真机无TIME列不影响解析():
    r = p.parse_ps(REAL_PS)
    assert [x["pid"] for x in r["procs"]][:5] == [1, 2, 3, 5, 8]


def test_ps_内核线程方括号短名不被斜杠切碎():
    """`[ksoftirqd/0]` 的短名必须是 `ksoftirqd/0`，不能被 rsplit('/') 切成 `0]`。"""
    r = p.parse_ps(REAL_PS)
    comm = {x["pid"]: x["comm"] for x in r["procs"]}
    assert comm[3] == "ksoftirqd/0"
    assert comm[11] == "ksoftirqd/1"
    assert comm[5] == "kworker/0:0H"
    assert comm[16] == "kworker/0:1H"
    assert comm[2] == "kthreadd"          # 无斜杠的方括号也要剥掉
    assert comm[14] == "rcu_bh"
    assert comm[9] == "rcu_sched"


def test_ps_真机用户态短名去路径前缀():
    r = p.parse_ps(REAL_PS)
    comm = {x["pid"]: x["comm"] for x in r["procs"]}
    assert comm[1] == "procd"
    assert comm[275] == "ubusd"
    assert comm[697] == "rpcd"
    assert comm[742] == "hostapd"
    assert comm[2552] == "hostapd_cli"


def test_ps_真机长命令行含空格完整保留():
    r = p.parse_ps(REAL_PS)
    args = {x["pid"]: x["args"] for x in r["procs"]}
    assert args[742] == ("hostapd -g /var/run/hostapd/global -B "
                         "-P /var/run/hostapd")
    assert args[697] == "/usr/sbin/rpcd -t 30"


def test_ps_真机内核线程args保留原始方括号():
    r = p.parse_ps(REAL_PS)
    args = {x["pid"]: x["args"] for x in r["procs"]}
    assert args[3] == "[ksoftirqd/0]"


def test_ps_汇总行不计入进程():
    text = REAL_PS + "   17 processes\n"
    r = p.parse_ps(text)
    assert r["count"] == 17
    assert "processes" not in {x["args"] for x in r["procs"]}


def test_ps_两种真机表头都兼容():
    """`VSZ STAT` 表头与老固件 `TIME` 表头必须给出同样的进程数与 comm。"""
    real = p.parse_ps(REAL_PS)
    legacy = p.parse_ps(
        "  PID USER     TIME  COMMAND\n"
        "    1 root      0:00 /sbin/procd\n"
        "    2 root      0:00 [kthreadd]\n"
        "    3 root      0:00 [ksoftirqd/0]\n")
    assert legacy["count"] == 3
    assert {x["comm"] for x in legacy["procs"]} == {"procd", "kthreadd", "ksoftirqd/0"}
    assert [x["args"] for x in legacy["procs"]] == [x["args"] for x in real["procs"]][:3]


# ── Bug 4: 服务列表真机（ls ANSI 色码） ─────────────────────────────

def test_service_list_真机ANSI色码被剥离():
    r = services.parse_service_list(REAL_LS_INITD)
    assert r == ["auto_speedtest", "autovpn", "boot", "boot_check",
                 "cab_meshd", "cgroup_init", "messagingagent.sh",
                 "qca-hostapd", "qca-nss-drv", "syslog-ng"]


def test_service_list_真机名含点与连字符():
    r = services.parse_service_list(REAL_LS_INITD)
    assert "messagingagent.sh" in r
    assert "qca-hostapd" in r
    assert "qca-nss-drv" in r
    assert "syslog-ng" in r


def test_service_list_色码不残留():
    for name in services.parse_service_list(REAL_LS_INITD):
        assert "\x1b" not in name


def test_service_list_仍过滤注入型名字():
    r = services.parse_service_list(
        "network\na;b\n\x1b[1;32mdnsmasq\x1b[0m\n../../etc/passwd\n")
    assert r == ["network", "dnsmasq"]


def test_list_command_不依赖ls的颜色选项():
    """命令侧也要换掉：某些 BusyBox 的 ls 不认 --color=never。"""
    cmd = services.list_command()
    assert "/etc/init.d" in cmd
    assert "--color" not in cmd
    assert "basename" in cmd


# ── Bug 5: wifi 状态命令真机（ifconfig 不认单引号） ──────────────────

def test_build_state_command_接口名不带单引号():
    """本机 BusyBox 的 ifconfig 把 'wl0' 当接口名的一部分，加引号等于查不到。"""
    cmd = wifi.build_state_command()
    assert "ifconfig 'wl0'" not in cmd
    assert "'wl0'" not in cmd
    assert "ifconfig wl0" in cmd
    assert "ifconfig wl1" in cmd


def test_build_state_command_保留ps段与标记():
    cmd = wifi.build_state_command()
    assert "---PS---" in cmd
    assert "grep hostapd" in cmd
    assert "grep -v grep" in cmd


def test_build_state_command_接口名仍过白名单():
    cmd = wifi.build_state_command(["wl0", "a; reboot", "wl1"])
    assert "ifconfig wl0" in cmd
    assert "ifconfig wl1" in cmd
    assert "reboot" not in cmd


# ── Bug 6: any_up 语义（enslaved 拓扑下 wlan 接口没有 IPv4） ─────────

def test_wifi_state_enslaved拓扑下any_up为真():
    """wl0/wl1 被 enslaved 到 br-lan，IPv4 在 br-lan 上；hostapd 在跑就算开。"""
    st = wifi.parse_wifi_state(REAL_IFCONFIG_WL, REAL_PS_HOSTAPD)
    assert st["hostapd"] is True
    assert st["any_up"] is True


def test_wifi_state_enslaved拓扑下ifaces无inet():
    st = wifi.parse_wifi_state(REAL_IFCONFIG_WL, REAL_PS_HOSTAPD)
    assert st["ifaces"]["wl0"] == {"inet": None, "netmask": None}
    assert st["ifaces"]["wl1"] == {"inet": None, "netmask": None}


def test_wifi_state_hostapd在跑但接口没inet也算开():
    """OR 语义：只靠 hostapd 就能判定开启。"""
    st = wifi.parse_wifi_state(REAL_IFCONFIG_WL, REAL_PS_HOSTAPD)
    assert not any(v["inet"] for v in st["ifaces"].values())
    assert st["any_up"] is True


def test_wifi_state_hostapd停了且无inet才算关():
    st = wifi.parse_wifi_state(REAL_IFCONFIG_WL, "  275 root 3092 S /sbin/ubusd\n")
    assert st["hostapd"] is False
    assert st["any_up"] is False


def test_wifi_state_无ps输入时退回看inet():
    """没采 ps（ps_text=None）时退回「任一 wlan 接口有 inet」这一条判据。

    注意 br-lan 的 inet **不在** WIFI_IFACES 里，本机 IP 全在网桥上，所以这条判据
    在本机同样为 False —— 换言之 `ps_text` 是必需的，只给 ifconfig 判不出开启。
    """
    full = REAL_IFCONFIG_WL + "\n" + REAL_IFCONFIG_BR
    with_ps = wifi.parse_wifi_state(full, REAL_PS_HOSTAPD)
    no_ps = wifi.parse_wifi_state(full)
    assert no_ps["hostapd"] is None
    assert isinstance(no_ps["any_up"], bool)
    assert with_ps["any_up"] is True          # hostapd 判据成立
    assert no_ps["any_up"] is False           # br-lan 的 inet 不算 wlan 接口的
    assert no_ps["ifaces"] == with_ps["ifaces"]


def test_wifi_state_键名与类型不变():
    st = wifi.parse_wifi_state(REAL_IFCONFIG_WL, REAL_PS_HOSTAPD)
    assert set(st) == {"ifaces", "hostapd", "any_up"}
    assert isinstance(st["any_up"], bool)
    assert isinstance(st["hostapd"], bool)
    assert set(st["ifaces"]) == set(wifi.WIFI_IFACES)


def test_wifi_state_空输出也给出完整结构():
    st = wifi.parse_wifi_state("", None)
    assert set(st) == {"ifaces", "hostapd", "any_up"}
    assert st["any_up"] is False
    assert st["hostapd"] is None


# ── 合并输出的正确消费方式（真机复验踩过的坑） ───────────────────────
#
# 真机复验时我曾把 `build_state_command()` 的整段输出直接喂给
# `parse_wifi_state()` 当第一个参数，于是 ps 段被当成 ifconfig 文本的一部分、
# `ps_text` 保持默认 None -> `hostapd` 为 None、`any_up` 退回「只看 inet」。
# 而本机 wl0/wl1 已 enslaved 到 br-lan、自身不持 IPv4，那条判据恒为 False，
# 于是 Wi-Fi 明明在跑却报 `any_up is False`。`split_state_output()` 把这条
# 唯一正确的消费方式固定下来。

def test_split_state_output_合并输出能拆出两段():
    combined = REAL_IFCONFIG_WL + "\n" + wifi.PS_MARKER + "\n" + REAL_PS_HOSTAPD
    ifc, ps = wifi.split_state_output(combined)
    assert "wl0" in ifc and "hostapd" not in ifc
    assert "hostapd" in ps
    st = wifi.parse_wifi_state(ifc, ps)
    assert st["hostapd"] is True
    assert st["any_up"] is True


def test_split_state_output_无标记时ps段为空串():
    ifc, ps = wifi.split_state_output(REAL_IFCONFIG_WL)
    assert ps == ""
    assert "wl0" in ifc
    assert wifi.parse_wifi_state(ifc, ps)["hostapd"] is False


def test_split_state_output_空输入不抛异常():
    assert wifi.split_state_output("") == ("", "")
    assert wifi.split_state_output(None) == ("", "")


def test_build_state_command_用的就是PS_MARKER():
    """标记必须与拆分函数同源，否则拆不开。"""
    assert wifi.PS_MARKER in wifi.build_state_command()


# ── 纯函数性质（真机样本同样不得抛异常） ─────────────────────────────

@pytest.mark.parametrize("bad", [
    "", "   \n\n", None, "\x00\x01", "root@XiaoQiang:~# ",
    "\x1b[1;32mauto_speedtest\x1b[0m",
])
def test_真机样本下各解析器不抛异常(bad):
    p.parse_proc_stat(bad, None)
    p.parse_ps(bad)
    services.parse_service_list(bad)
    wifi.parse_wifi_state(bad, bad)
    wifi.parse_iface_map(bad)
