"""router_admin 采集层（网络/终端侧）：纯文本 → 结构化数据。
与 `parsers.py` 同约定：纯函数、不做 I/O、失败返回 None/[]、绝不抛异常；
`parsers.py` re-export 本文件全部公开名，调用方只需 `from . import parsers`。
"""
import re

_RE_ARP_IP = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_RE_MAC = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
_RE_IPV4 = r"\d+\.\d+\.\d+\.\d+"
_RE_IPV6 = r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}"


def parse_ifconfig(text):
    """`ifconfig` → `[{iface,inet,netmask,mac,mtu,hwaddr_hwtype,inet6}]`。

    以「顶格且含 `Link encap:` 的行」切分网卡块，缩进行归属上一块；顶格但不是
    网卡头的行（`ifconfig: not found` 等报错）整体忽略。无 inet 的网卡也收录。
    inet6 只取 `Scope: Global` 的全局地址。
    """
    rows = []
    cur = None
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        head = re.match(r"^(\S+)\s+\S", raw)
        encap = re.search(r"Link encap:(\S+)", raw)
        if head and encap:
            cur = {"iface": head.group(1), "inet": None, "netmask": None,
                   "mac": None, "mtu": None, "inet6": None,
                   "hwaddr_hwtype": encap.group(1)}
            rows.append(cur)
            _take_hw(cur, raw)
            continue
        if cur is None or head:
            continue          # 顶格且非网卡头：报错文本等，忽略
        _take_hw(cur, raw)
    return rows


def _take_hw(cur, line):
    """从一行 ifconfig 续行里抽取 mac/inet/netmask/mtu/inet6。"""
    m = re.search(r"HWaddr\s+([0-9A-Fa-f:]{17})", line)
    if m:
        cur["mac"] = m.group(1)
    m = re.search(r"inet\s+(?:addr:)?" + "(" + _RE_IPV4 + ")", line)
    if m and cur["inet"] is None:
        cur["inet"] = m.group(1)
    m = re.search(r"Mask:(" + _RE_IPV4 + ")", line)
    if m:
        cur["netmask"] = m.group(1)
    m = re.search(r"MTU:(\d+)", line)
    if m:
        cur["mtu"] = int(m.group(1))
    m = re.search(r"inet6 addr:\s*(" + _RE_IPV6 + r")(?:/\d+)?\s+Scope:\s*(\w+)", line)
    if m and cur["inet6"] is None and m.group(2).lower() == "global":
        cur["inet6"] = m.group(1)


def parse_arp(text):
    """`/proc/net/arp` → `[{ip,mac,dev,complete}]`。
    flags 最低位（`0x2`）置位即条目完整（= 在线）；未完成条目保留，由调用方过滤。
    """
    rows = []
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) < 6 or not _RE_ARP_IP.match(f[0]):
            continue
        try:
            flags = int(f[2], 16)
        except ValueError:
            continue
        rows.append({"ip": f[0], "mac": f[3], "dev": f[5],
                     "complete": bool(flags & 0x2)})
    return rows


def parse_dnsmasq_leases(text):
    """dnsmasq 租约文件 → `[{mac,ip,hostname,expires}]`；主机名为 `*` 时置 None。

    列序按内容嗅探两种常见排布：`<mac> <ip> <hostname> <expiry> <name>`（任务书给定）
    与 `<expiry> <mac> <ip> <hostname> <client-id>`（dnsmasq 标准）。
    """
    rows = []
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) < 4:
            continue
        if _RE_MAC.match(f[0]):
            mac, ip, host, expires = f[0], f[1], f[2], f[3]
        elif len(f) >= 5 and _RE_MAC.match(f[1]):
            mac, ip, host, expires = f[1], f[2], f[3], f[0]
        else:
            continue
        if not _RE_ARP_IP.match(ip):
            continue
        try:
            expires = int(expires)
        except ValueError:
            pass
        rows.append({"mac": mac, "ip": ip,
                     "hostname": None if host in ("*", "") else host,
                     "expires": expires})
    return rows


#: BusyBox 部分版本的 `ps` 末尾有进程数汇总行（`   17 processes`），需剔除
_PS_SUMMARY_RE = re.compile(r"^\s*\d+\s+processes?\b", re.I)


def parse_ps(text):
    """`ps` → `{"procs":[{"pid","comm","args"}], "count": int}`；无表头返回 None。

    按**表头里实际存在的列名**定位字段，同时兼容 `PID USER VSZ STAT COMMAND`
    （BusyBox v1.25.1 真机，**无 TIME 列**）与 `PID USER TIME COMMAND`（老固件）。
    COMMAND 列及其后的内容原样保留（命令行含空格，绝不按空白截断）。`comm` 取独立
    COMM 列（若有），否则由 COMMAND 首段派生（见 `_ps_comm`）——真机的内核线程短名
    **带斜杠**（`[ksoftirqd/0]`），早先用 `rsplit("/")` 会被切成 `0]`。
    """
    lines = (text or "").splitlines()
    header = next(([c.upper() for c in l.split()] for l in lines
                   if l.split() and l.split()[0].upper() == "PID"), None)
    if header is None:
        return None
    args_idx = _col_index(header, ("ARGS", "CMDLINE"))
    if args_idx is None:
        args_idx = _col_index(header, ("COMMAND", "CMD"))
    if args_idx is None:
        args_idx = len(header) - 1
    comm_idx = _col_index(header, ("COMM",))
    if comm_idx is not None and comm_idx > args_idx:
        comm_idx = None                      # COMM 排在 COMMAND 之后：不是短名列
    procs = []
    for line in lines:
        f = line.split()
        if len(f) <= args_idx or f[0].upper() == "PID":
            continue
        if _PS_SUMMARY_RE.match(line):
            continue                          # BusyBox 的「N processes」汇总行
        try:
            pid = int(f[0])
        except ValueError:
            continue
        if pid <= 0:
            continue
        args = " ".join(f[args_idx:])
        comm = f[comm_idx] if (comm_idx is not None and len(f) > comm_idx) \
            else _ps_comm(args)
        procs.append({"pid": pid, "comm": comm, "args": args})
    return {"procs": procs, "count": len(procs)}


def _ps_comm(args):
    """由 COMMAND 首段派生短名：内核线程去方括号，用户进程去路径前缀。"""
    name = args.split()[0]                    # 调用方保证 args 非空
    if name.startswith("[") and name.endswith("]"):
        return name[1:-1]                    # [ksoftirqd/0] -> ksoftirqd/0
    return name.rsplit("/", 1)[-1]           # /sbin/procd -> procd


def _col_index(header, names):
    for i, col in enumerate(header):
        if col in names:
            return i
    return None


def parse_df(text):
    """`df -k` → `[{mount,total_kb,used_kb,avail_kb,use_pct}]`。

    按「四个数值列」（total used avail use%）定位数据，不依赖列宽；BusyBox 会把过长的
    Filesystem 折到上一行、或把挂载点折到下一行，两种都归并（折行的 Filesystem 名
    不产出字段，本函数的语义键只有 mount）。
    """
    rows = []
    deferred = None      # 四元组已读到但挂载点还欠着（等下一行）
    for line in (text or "").splitlines():
        f = line.split()
        if not f or f[0] in ("Filesystem", "Mounted"):
            continue
        nums = _df_numbers(f)
        if nums is None:
            if deferred and len(f) == 1 and f[0].startswith("/"):
                rows.append(_df_row(deferred, f[0]))
                deferred = None
            continue
        if not nums[4]:                       # 挂载点折到下一行
            deferred = nums[:4]
            continue
        rows.append(_df_row(nums[:4], " ".join(nums[4])))
        deferred = None
    return rows


def _df_row(nums, mount):
    total, used, avail, use_pct = nums
    return {"mount": mount, "total_kb": total, "used_kb": used,
            "avail_kb": avail, "use_pct": use_pct}


def _df_numbers(tokens):
    """在 token 序列里找 `总数 已用 可用 使用率%` 四个数值列，返回 (值..., 挂载点)。"""
    for i in range(len(tokens) - 3):
        head, use = tokens[i:i + 3], tokens[i + 3]
        if not all(v.isdigit() for v in head):
            continue
        if not use.endswith("%") or not use[:-1].isdigit():
            continue
        return (int(head[0]), int(head[1]), int(head[2]),
                int(use[:-1]), tokens[i + 4:])
    return None


def parse_uptime_fmt(seconds):
    """秒数 → `"3 天 4 时 5 分"` / `"4 时 5 分"` / `"5 分"`；非法输入返回 `—`。"""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    parts = [f"{hours} 时"] if (days or hours) else []
    if days:
        parts.insert(0, f"{days} 天")
    parts.append(f"{rest // 60} 分")
    return " ".join(parts)


def merge_clients(arp, leases):
    """ARP + 租约 → 终端列表 `[{ip,mac,hostname,dev}]`。

    按 IP 关联，**优先用 dnsmasq 主机名**；无租约的仍列出（MAC 兜底、hostname 为
    None）。只保留 complete 的 ARP 项（不完整 = 离线）。
    """
    by_ip = {(i or {}).get("ip"): i for i in (leases or []) if (i or {}).get("ip")}
    rows = []
    for item in (arp or []):
        if not (item or {}).get("complete"):
            continue
        lease = by_ip.get(item.get("ip"))
        rows.append({
            "ip": item.get("ip"),
            "mac": item.get("mac") or (lease or {}).get("mac"),
            "hostname": (lease or {}).get("hostname") if lease else None,
            "dev": item.get("dev"),
        })
    return rows
