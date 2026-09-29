"""router_admin 采集层：纯文本 → 结构化数据（纯函数，全部可离线单测）。

规格：docs/superpowers/specs/2026-09-29-router-admin-design.md 第 6 节。

约定（全模块一致）：
- 全部是纯函数：输入 str（可能为 None/空/命令报错文本），输出 dict/list，**不做 I/O**；
- 解析失败返回 None 或 []，**绝不抛异常**——单项失败只让该项显示为「—」，
  不影响同一轮其它指标；
- 不假设新内核字段（MemAvailable 缺失回落）、不假设列存在（ps 无 CPU% 列）、
  不假设输出不折行（df -k）。

本文件放系统资源类（/proc），网络/终端类在 `parsers_net.py`，公开名在此 re-export，
调用方统一 `from . import parsers`。
"""
import re

from .parsers_net import (merge_clients, parse_arp, parse_df,
                          parse_dnsmasq_leases, parse_ifconfig, parse_ps,
                          parse_uptime_fmt)

__all__ = [
    "parse_uptime", "parse_meminfo", "parse_proc_stat", "parse_loadavg",
    "parse_net_dev", "parse_ifconfig", "parse_arp", "parse_dnsmasq_leases",
    "parse_ps", "parse_df", "parse_uptime_fmt", "merge_clients",
]


def parse_uptime(text):
    """`/proc/uptime` → `{"uptime_s": float}`（第一列秒数含小数）。"""
    parts = (text or "").split()
    if not parts:
        return None
    try:
        return {"uptime_s": float(parts[0])}
    except ValueError:
        return None


def parse_meminfo(text):
    """`/proc/meminfo` → 内存字典。

    `available_kb` 优先取 MemAvailable；老内核没有该字段时回落为
    MemFree + Buffers + Cached。`used_pct = 100*(total-available)/total`（1 位小数）。
    """
    fields = {}
    for line in (text or "").splitlines():
        m = re.match(r"^(\S+):\s+(\d+)", line)
        if m:
            fields[m.group(1)] = int(m.group(2))
    total = fields.get("MemTotal")
    if not total:
        return None
    free = fields.get("MemFree", 0)
    cached = fields.get("Cached", 0)
    if "MemAvailable" in fields:
        available = fields["MemAvailable"]
    else:
        available = free + fields.get("Buffers", 0) + cached
    used_pct = round(100.0 * (total - available) / total, 1)
    return {
        "total_kb": total,
        "free_kb": free,
        "available_kb": available,
        "cached_kb": cached,
        "slab_kb": fields.get("Slab", 0),
        "used_pct": used_pct,
    }


#: `/proc/stat` 聚合行至少要有 user nice system idle 四个 jiffies 列
_CPU_MIN_FIELDS = 4


def _cpu_jiffies(text):
    """`/proc/stat` 聚合行 `cpu` → `{"total": int, "idle": int}`（idle 含 iowait）。

    只取聚合行（首 token 恰为 `cpu`），跳过 `cpu0`/`cpu1` 等分核行。
    字段一律按 **任意空白** 切分：本机 BusyBox 的聚合行是 `cpu␠␠634498 …`
    （`cpu` 与首个数字之间有两个空格），用 `startswith("cpu ")` + 定宽切分都会踩空。
    """
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) < 1 + _CPU_MIN_FIELDS or f[0] != "cpu":
            continue
        try:
            nums = [int(v) for v in f[1:]]
        except ValueError:
            continue                          # 脏行：继续找后面的聚合行
        if len(nums) < _CPU_MIN_FIELDS:
            continue
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return {"total": sum(nums), "idle": idle}
    return None


def _prev_jiffies(prev):
    """把 `prev` 归一成 `{"total","idle"}`；没有可用历史时返回 None（**不抛异常**）。

    `prev` 可为原始 `/proc/stat` 文本、`{"total","idle"}` 字典、None/""。
    字典里**没有** total/idle（例如上一次返回的 `{"cpu_pct": 5.0}`）时返回 None
    —— 旧实现直接 `prev["total"]` 会抛 `KeyError`，违反本模块「绝不抛异常」的契约。
    """
    if isinstance(prev, dict):
        if "total" not in prev or "idle" not in prev:
            return None
        try:
            return {"total": int(prev["total"]), "idle": int(prev["idle"])}
        except (TypeError, ValueError):
            return None
    if not prev:
        return None
    return _cpu_jiffies(prev)


def parse_proc_stat(text, prev):
    """`/proc/stat` 采样 → 有历史时 `{"cpu_pct": float}`，无历史时返回**基线字典**。

    `cpu_pct = 100 * (1 - Δidle/Δtotal)`（1 位小数）。

    `prev` 传上一次采样的原始文本、或上一次返回的基线字典
    （`{"cpu_pct": None, "total": int, "idle": int}`）。

    **为什么首调不再返回 None**：老 BusyBox 的 `ps` 没有 CPU% 列，CPU 占用率只能
    靠「两次采样 jiffies 差值」算出来；若首调用 None，调用方手里就没有任何东西
    可存下来当下一轮的 `prev`，占用率会永远是「—」。故首调（`prev` 为空、不可解析、
    或 Δtotal ≤ 0）统一返回**本次的 jiffies 基线**，`cpu_pct` 为 None（UI 显示「—」），
    把它原样回传即可在下轮拿到数值。

    只有 `text` 里根本没有可解析的 `cpu` 聚合行时（垃圾输入保护）才返回 None。
    """
    cur = _cpu_jiffies(text)
    if cur is None:
        return None
    pre = _prev_jiffies(prev)
    if pre is not None:
        dt = cur["total"] - pre["total"]
        if dt > 0:
            pct = round(100.0 * (1.0 - (cur["idle"] - pre["idle"]) / dt), 1)
            return {"cpu_pct": pct}
    return {"cpu_pct": None, "total": cur["total"], "idle": cur["idle"]}


def parse_loadavg(text):
    """`/proc/loadavg` → `{"load1","load5","load15"}`（float）；不可读返回 None。"""
    parts = (text or "").split()
    if len(parts) < 3:
        return None
    try:
        return {"load1": float(parts[0]), "load5": float(parts[1]),
                "load15": float(parts[2])}
    except ValueError:
        return None


def parse_net_dev(text):
    """`/proc/net/dev` → 每接口一行 `[{iface,rx_*,tx_*,errs,drop}]`。

    接口名带冒号（`eth0:`）必须按**第一个**冒号切分；`lo` 也保留，由调用方过滤。
    假定：`errs`/`drop` 取**接收侧**（rx）的错误与丢包计数（tx 侧另有 errs/drop，
    规格未要求分开列，故未收）。
    """
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if not name or " " in name:
            continue
        cols = rest.split()
        if len(cols) < 10:
            continue
        try:
            nums = [int(c) for c in cols[:16]]
        except ValueError:
            continue
        rows.append({
            "iface": name,
            "rx_bytes": nums[0], "tx_bytes": nums[8],
            "rx_pkt": nums[1], "tx_pkt": nums[9],
            "errs": nums[2], "drop": nums[3],
        })
    return rows
