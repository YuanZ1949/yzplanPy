"""router_admin/wifi：无线状态读取 + 开关命令 + 断连自恢复回滚。

`wifi down` 会停掉 hostapd，AP 消失 → 我们自己的 telnet（走 br-lan）随之断开，
用户可能再也连不回来。因此关闭/重启前**必须先在远端挂一个与当前 shell 解绑的
回滚任务**：45 秒后自动 `wifi up`。用户 60 秒内重连成功可手动取消回滚。

回滚用 PID 标记文件定位，不用 pgrep 模糊匹配，避免误杀其他进程。
"""
import re

#: 关注的无线路由接口名
WIFI_IFACES = ("wl0", "wl1")

#: 回滚标记文件（存回滚子进程 PID）
ROLLBACK_MARKER = "/tmp/yzp_wifi_rollback"

#: 回滚延迟（秒）
ROLLBACK_DELAY = 45

#: `build_state_command()` 输出里 ifconfig 段与 ps 段之间的分隔标记。
#: 消费该命令的输出**必须**用 `split_state_output()` 拆分后再传给
#: `parse_wifi_state()`：本机 wl0/wl1 已 enslaved 到 br-lan、自身不持 IPv4，
#: 漏掉 ps 段时 `any_up` 只能退回「看 inet」这一条判据，在本机恒为 False
#: ——Wi-Fi 明明在跑却会显示已关闭。
PS_MARKER = "---PS---"

VALID_ACTIONS = ("up", "down", "restart")

_IFCONFIG_RE = re.compile(r"^(\S+)\s+Link encap", re.M)
_INET_RE = re.compile(
    r"inet addr:(\d+\.\d+\.\d+\.\d+)\s+Bcast:\d+\.\d+\.\d+\.\d+\s+Mask:(\S+)")


class WifiError(ValueError):
    """无线操作参数非法。"""


def parse_iface_map(text):
    """`ifconfig` 输出 -> {iface: {"inet": str|None, "netmask": str|None}}。"""
    blocks = {}
    for match in _IFCONFIG_RE.finditer(text or ""):
        blocks[match.group(1)] = {"inet": None, "netmask": None}
    for match in _INET_RE.finditer(text or ""):
        if match.group(1) in blocks:
            blocks[match.group(1)]["inet"] = match.group(1)
            blocks[match.group(1)]["netmask"] = match.group(2)
    return blocks


def hostapd_running(ps_text):
    """ps 输出里是否有 hostapd 进程。"""
    for line in (ps_text or "").splitlines():
        if "hostapd" in line and "grep" not in line:
            return True
    return False


def parse_wifi_state(ifconfig_text, ps_text=None):
    """综合 ifconfig + ps -> {"ifaces": {...}, "hostapd": bool|None, "any_up": bool}。

    **`any_up`（无线「开着」）= hostapd 在跑 或 任一 wlan 接口持有 IPv4 —— 或关系。**

    为什么是「或」而不是原来的「且」：本机（小米小胖 / OpenWrt）的 `wl0`/`wl1`
    已被 enslaved 到网桥 `br-lan`，**自身不持有任何 IPv4 地址**（IPv4 全在 br-lan 上，
    wlan 接口只有一条 `inet6 ... Scope:Link`）。老语义要求「hostapd 在跑 **且** 至少
    一个 wlan 接口有 inet」，在这种拓扑下第二条件恒不成立，`any_up` **恒为 False**
    ——Wi-Fi 明明在正常工作，UI 却显示已关闭。

    两个判据各自的误判场景：
      - 只看 hostapd：AP 刚起、hostapd 尚未 fork 完成的瞬间会误判为关（几百毫秒）；
      - 只看 inet：客户端未接入时误判为关。
    取「或」后两者都不再造成持续误判：关窗时 hostapd 被 `wifi down` 停掉、无线接口
    也无 inet，两条都不成立，仍然正确判为关。

    `hostapd` 键：`ps_text` 为 None 时（调用方没采 ps）为 None，否则是 bool。
    `ifaces` 恒含 `WIFI_IFACES` 里的每个接口名，取不到时 `inet`/`netmask` 为 None。
    """
    blocks = parse_iface_map(ifconfig_text)
    ifaces = {name: blocks.get(name, {"inet": None, "netmask": None})
              for name in WIFI_IFACES}
    ap = hostapd_running(ps_text) if ps_text is not None else None
    any_ip = any(v["inet"] for v in ifaces.values())
    up = any_ip if ap is None else bool(ap) or any_ip
    return {"ifaces": ifaces, "hostapd": ap, "any_up": bool(up)}


def build_state_command(ifaces=WIFI_IFACES):
    """一次 batch 取无线状态（ifconfig 各接口 + hostapd 进程）。

    接口名**不带引号**：本机 BusyBox 的 `ifconfig` 不做 shell 风格的引号剥离，会把
    `'wl0'` 整个当成接口名的一部分 → 查不到接口，报错又被 `2>/dev/null` 吞掉，整条
    命令的 ifconfig 段全空。接口名先过白名单正则 `^[A-Za-z0-9_.-]+$`（**无命令注入
    风险**），因此不需要引号。每个接口单独一条 `ifconfig`，不依赖 BusyBox ifconfig
    是否支持多接口参数。
    """
    names = [n for n in ifaces if re.match(r"^[A-Za-z0-9_.-]+$", n)]
    head = "".join(f"ifconfig {n} 2>/dev/null; " for n in names)
    return (f"{head}echo '{PS_MARKER}'; "
            f"ps 2>/dev/null | grep hostapd | grep -v grep")


def split_state_output(text):
    """把 `build_state_command()` 的合并输出拆成 (ifconfig_text, ps_text)。

    配套 `build_state_command` / `parse_wifi_state` 使用。**必须**经本函数拆分
    后再调 `parse_wifi_state(ifconfig_text, ps_text)`：ps 段是 `any_up` 在本机
    拓扑（wl0/wl1 enslaved 到 br-lan、自身无 IPv4）下唯一成立的判据，漏掉它
    会让「Wi-Fi 已关闭」被永久误报。输出里没有标记时 ps 段返回空串。
    """
    ifconfig_text, _, ps_text = (text or "").partition(PS_MARKER)
    return ifconfig_text, ps_text


def build_wifi_command(action):
    """构造 `wifi up` / `wifi down` / `wifi down && sleep 2 && wifi up`。"""
    action = (action or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise WifiError(f"非法无线动作：{action!r}")
    if action == "up":
        return "wifi up 2>&1"
    if action == "down":
        return "wifi down 2>&1"
    return "wifi down 2>&1; sleep 2; wifi up 2>&1"


def build_rollback_arm_command(delay=ROLLBACK_DELAY):
    """挂起与当前 shell 解绑的回滚任务，返回其 PID。

    `( ... ) &` 让子进程脱离会话：即便 telnet 断开，sleep 与随后的 wifi up
    依然会执行。`$!` 取到的正是这个子进程 PID，写进标记文件供取消时 kill。
    """
    delay = int(delay)
    if not 5 <= delay <= 600:
        raise WifiError(f"回滚延迟超出范围 5-600 秒：{delay}")
    return (f"rm -f {ROLLBACK_MARKER}; "
            f"( sleep {delay}; wifi up >/dev/null 2>&1 ) >/dev/null 2>&1 & "
            f"echo $! > {ROLLBACK_MARKER}; cat {ROLLBACK_MARKER}")


def build_rollback_cancel_command():
    """按 PID 终止回滚任务并清除标记。"""
    return (f"if [ -f {ROLLBACK_MARKER} ]; then "
            f"kill $(cat {ROLLBACK_MARKER}) 2>/dev/null; "
            f"rm -f {ROLLBACK_MARKER}; echo CANCELLED; "
            f"else echo NONE; fi")


def build_rollback_query_command():
    """查询回滚是否已挂起，返回 PID 文本。"""
    return f"cat {ROLLBACK_MARKER} 2>/dev/null || echo NONE"


def parse_rollback_state(text):
    """解析回滚查询输出 -> {"armed": bool, "pid": int|None}。"""
    raw = (text or "").strip().split()
    if not raw:
        return {"armed": False, "pid": None}
    token = raw[-1].strip()
    if token.upper() == "NONE":
        return {"armed": False, "pid": None}
    try:
        pid = int(token)
    except ValueError:
        return {"armed": False, "pid": None}
    if pid <= 0:
        return {"armed": False, "pid": None}
    return {"armed": True, "pid": pid}


def parse_arm_result(text):
    """解析挂起命令的输出 -> {"armed": bool, "pid": int|None}。"""
    return parse_rollback_state(text)
