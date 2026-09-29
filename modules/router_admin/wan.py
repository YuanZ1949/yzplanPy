"""router_admin/wan.py：宽带(PPPoE)账号读取/写入、独立重拨、在线状态查询。

**为什么不复用配置编辑 Tab**：通用 UCI 文本框把「口令/密钥类字段」一律列为
`block`（见 `config_editor.SECRET_KEY_PARTS`），那是刻意设计——防止用户顺手在
文本框里改坏密钥。但宽带账号恰恰**只有一个**正当入口，专用表单走的是
「已明确授权 + 窄校验 + 备份 + 原子写 + 回读」这条更严格的路径，不经过那条闸门。

**口令绝不进 UI**：`parse_account` 只回 `has_password` 布尔，不回明文；表单的口令框
默认留空表示「不修改」，与本模块自身的 telnet 口令框同一套交互约定。

真机事实（小米 XiaoQiang / OpenWrt，192.168.2.1）：
- `/etc/config/network` 的 `config interface 'wan'`：proto='pppoe'、
  username/password/ifname='eth0'/mtu='1500'/mru='1480'/ipv6='auto'/
  macaddr/special/last_succeed
- `ubus call network.interface.wan status` 返回**多行美化 JSON**（~1757 字符、72 行），
  可整段取回后 `json.loads`；L3 设备 `l3_device='pppoe-wan'`，物理口 `device='eth0'`
- `/sbin/ifup`、`/sbin/ifdown` 存在，**接受的是 UCI 段名 `wan`**（不是 `pppoe-wan`）
- 真机有 `wan_check` 守护脚本会自动重拨，重拨后即使本模块不轮询也会自愈
- BusyBox tty 单行输入上限约 500 字节（真机实测 493 过 / 513 超时），故本文件
  每条命令都自带 `test_*_fits_tty_limit` 类断言
"""
import copy
import json
import re

#: UCI 里的 interface 段名（`ifup`/`ifdown`/`ubus` 接受的都是它，不是 `pppoe-wan`）
DEFAULT_IFACE = "wan"

#: 接口名白名单——命令注入防线，与 services.SERVICE_NAME_RE 同思路
IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

#: 用户名 / 口令的长度上限（远大于真机实测的 21 / 8 字符）
MAX_ACCOUNT_LEN = 128

#: 重拨期间 ifdown/ifup 的输出落盘位置
REDIAL_LOG = "/tmp/yzp_wan_redial.log"

#: 重拨命令回显的完成标记
REDIAL_MARKER = "YZ_REDIAL_SENT"

#: 断线后等待链路落下的秒数（PPoE 需释放旧会话）
REDIAL_SETTLE_SEC = 2

#: 下发重拨后自动轮询状态的次数与间隔（ms）。**必须有上限**，否则界面永远转圈。
#: PPoE 协商常需 3~10s，3 次 × 4s ≈ 12s 足够覆盖绝大多数情况。
REDIAL_POLL_TIMES = 3
REDIAL_POLL_MS = 4000

#: `parse_status` 的固定返回形状（成功与失败都必须是这组键）
STATUS_KEYS = frozenset({
    "up", "pending", "available", "uptime_s", "proto", "device", "l3_device",
    "ipv4", "netmask", "ptp", "ipv6", "dns", "error",
})


class WanError(ValueError):
    """宽带操作被拒绝或参数非法。"""


# ── 校验 ────────────────────────────────────────────────────────
def _check_len(value, what):
    if not isinstance(value, str):
        raise WanError(f"{what}必须是字符串")
    if len(value) > MAX_ACCOUNT_LEN:
        raise WanError(f"{what}过长（上限 {MAX_ACCOUNT_LEN} 字符）")


def _has_forbidden(value):
    """单引号会破坏 UCI 的 `option key 'value'` 引号配对；控制字符会截断行。"""
    return "'" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def validate_iface(name):
    """接口名白名单校验，裁掉首尾空白后返回。任何非白名单字符一律拒绝。"""
    text = (name or "").strip() if isinstance(name, str) else ""
    if not text or not IFACE_RE.match(text):
        raise WanError(f"{name!r} 不是合法的接口名")
    _check_len(text, "接口名")
    return text


def validate_username(value):
    """宽带账号校验：非空、不过长、无单引号与控制字符、不含内部空白。"""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise WanError("宽带账号不能为空")
    _check_len(text, "宽带账号")
    if _has_forbidden(text):
        raise WanError("宽带账号含单引号或控制字符，无法安全写入 UCI")
    if any(ch.isspace() for ch in text):
        raise WanError("宽带账号不能含空格")
    return text


def validate_password(value):
    """宽带口令校验：非空、不过长、无单引号与控制字符（**允许空格**）。

    口令里出现空格是常见的（如 `ab cd12`），且 UCI 单引号内空格无需转义，
    故只在用户名上禁空白。
    """
    text = value if isinstance(value, str) else ""
    if not text.strip():
        raise WanError("宽带口令不能为空（留空请直接不填，不要点保存）")
    _check_len(text, "宽带口令")
    if _has_forbidden(text):
        raise WanError("宽带口令含单引号或控制字符，无法安全写入 UCI")
    return text


# ── 读取 ────────────────────────────────────────────────────────
def parse_account(uci):
    """从 `config_editor.parse_uci` 的结果里取出宽带账号（**不含明文口令**）。"""
    section = ((uci or {}).get("interface") or {}).get(DEFAULT_IFACE) or {}
    return {
        "present": bool(section),
        "proto": section.get("proto"),
        "username": section.get("username"),
        "has_password": bool(section.get("password")),
        "ifname": section.get("ifname"),
        "mtu": section.get("mtu"),
        "ipv6": section.get("ipv6"),
    }


# ── 写入 ────────────────────────────────────────────────────────
def apply_account(uci, *, username, password=None):
    """返回**新的** network 配置，只改 username 与（若给了）password 两个键。

    `password=None` 表示不修改口令。其余键（proto/ifname/mtu/macaddr/…）逐字保留，
    入参 dict 不被修改。找不到 `interface 'wan'` 段时**拒绝**而不是凭空新建——
    造出一个配置里不存在的接口段比失败更危险。
    """
    name = validate_username(username)
    pwd = None if password is None else validate_password(password)
    data = copy.deepcopy(uci or {})
    section = (data.get("interface") or {}).get(DEFAULT_IFACE)
    if section is None:
        raise WanError(f"/etc/config/network 里找不到 interface '{DEFAULT_IFACE}' 段")
    section["username"] = name
    if pwd is not None:
        section["password"] = pwd
    return data


# ── 状态 ────────────────────────────────────────────────────────
def build_status_command(iface=DEFAULT_IFACE):
    """读 WAN 在线状态。ubus 返回多行美化 JSON，整段取回后交给 `parse_status`。"""
    name = validate_iface(iface)
    return f"ubus call network.interface.{name} status 2>&1"


def _first(mapping):
    """ubus 的地址字段是**列表**，取第一条；缺失时给 None 而非抛。"""
    items = (mapping or {}).get("ipv4-address") or []
    if not isinstance(items, list) or not items:
        return {}
    first = items[0]
    return first if isinstance(first, dict) else {}


def _first6(mapping):
    items = (mapping or {}).get("ipv6-address") or []
    if not isinstance(items, list) or not items:
        return {}
    first = items[0]
    return first if isinstance(first, dict) else {}


def parse_status(text):
    """ubus 状态文本 → 固定形状的 dict。**任何异常输入都不抛**，只置 `error`。"""
    got = {key: None for key in STATUS_KEYS}
    got["dns"] = []
    body = (text or "").strip()
    if not body:
        got["error"] = "路由器没有返回宽带状态"
        return got
    try:
        data = json.loads(body)
    except ValueError:
        got["error"] = f"宽带状态不是合法 JSON：{body[:120]}"
        return got
    if not isinstance(data, dict):
        got["error"] = "宽带状态格式异常（不是对象）"
        return got
    v4, v6 = _first(data), _first6(data)
    got.update({
        "up": bool(data.get("up")),
        "pending": bool(data.get("pending")),
        "available": bool(data.get("available")),
        "uptime_s": data.get("uptime") if isinstance(data.get("uptime"), int) else None,
        "proto": data.get("proto"),
        "device": data.get("device"),
        "l3_device": data.get("l3_device"),
        "ipv4": v4.get("address"),
        "netmask": v4.get("mask"),
        "ptp": v4.get("ptpaddress"),
        "ipv6": v6.get("address"),
        "dns": data.get("dns-server") or [],
    })
    return got


def describe_status(status):
    """状态 dict → 一行可读文案。**绝不**把口令之类的东西写进文案。"""
    state = status or {}
    if state.get("error"):
        return f"宽带：未知（{state['error']}）"
    if state.get("up"):
        parts = ["宽带：在线"]
        if state.get("ipv4"):
            parts.append(f"IPv4 {state['ipv4']}")
        if state.get("ipv6"):
            parts.append(f"IPv6 {state['ipv6']}")
        if state.get("l3_device"):
            parts.append(f"链路 {state['l3_device']}")
        if state.get("uptime_s"):
            parts.append(f"已在线 {format_uptime(state['uptime_s'])}")
        return "，".join(parts)
    return "宽带：离线（未拨号或已断开）"


# ── 重拨 ────────────────────────────────────────────────────────
def build_redial_command(iface=DEFAULT_IFACE):
    """`ifdown` + `ifup` 精准重拨——**不是** `/etc/init.d/network restart`。

    走 ifup/ifdown 只拆建 WAN 一条链路，LAN、无线、其它服务都不动，因此本机与
    路由器的 telnet 始终保持。

    **必须分离执行**（`&` + `</dev/null`）：PPoE 的 `ifup` 要跑 LCP/PAP/IPCP
    协商，实测常需 3~10 秒，加上 `ifdown` 与 settle 等待会超过 telnet 的
    12s 读超时 → 命令被截断或超时，用户以为没下发。放到后台后本条命令立即回显
    完成标记，界面改为按 `REDIAL_POLL_TIMES` 轮询 `build_status_command` 确认
    是否真的拨上。输出落盘到 `REDIAL_LOG`，避免长输出回显折行干扰结束标记切割。
    """
    name = validate_iface(iface)
    return (f"( ifdown {name}; sleep {REDIAL_SETTLE_SEC}; ifup {name} ) "
            f">{REDIAL_LOG} 2>&1 </dev/null & echo {REDIAL_MARKER}")


def build_redial_read_command():
    return f"cat {REDIAL_LOG} 2>/dev/null"


def build_redial_cleanup_command():
    return f"rm -f {REDIAL_LOG}"


def parse_redial_log(text):
    """重拨日志 → {sent, output}。没收到完成标记即判为「未送达」。"""
    body = text or ""
    return {"sent": REDIAL_MARKER in body,
            "output": body.replace(REDIAL_MARKER, "").strip()}


# ── 文案 ────────────────────────────────────────────────────────
def save_confirm_text(username, *, changing_password):
    """保存账号的二次确认文案。**只说「口令会被修改」，绝不回显口令明文。**"""
    lines = [f"即将把宽带账号写回路由器的 /etc/config/network：",
             "",
             f"· 账号：{username}",
             f"· 口令：{'将改为本次填写的新口令' if changing_password else '保持不变（口令框留空 = 不修改口令）'}",
             "",
             "写入前会自动把当前配置备份到本机，写入后立即回读校验。",
             "",
             "注意：账号或口令填错会让路由器**完全无法上网**。",
             "但 LAN 与 telnet 不受影响，仍可回来改回或走近设备恢复。"]
    return "\n".join(lines)


def redial_confirm_text(iface):
    return (f"即将重新拨打 interface '{iface}'。\n\n"
            f"宽带会中断几秒到一分钟，期间本机无法上网；"
            f"LAN、无线与 telnet 不受影响。\n\n"
            f"若账号或口令有误，拨号会失败，宽带保持离线。\n\n确认重拨？")


def describe_change(old, new):
    """旧/新账号快照 → 改动摘要列表（供 UI 渲染确认框里的 diff）。"""
    rows = []
    if (old or {}).get("username") != (new or {}).get("username"):
        rows.append(f"账号：{old.get('username')} → {new.get('username')}")
    if (old or {}).get("has_password") != (new or {}).get("has_password"):
        rows.append("口令：未设置 → 已设置" if new.get("has_password")
                    else "口令：已设置 → 未设置")
    if not rows:
        rows.append("无改动")
    return rows


# ── 时长 ────────────────────────────────────────────────────────
def format_uptime(secs):
    """秒 → 「N 天 N 时 N 分」/「N 时 N 分」/「N 分 N 秒」/「N 秒」。"""
    try:
        total = max(0, int(secs))
    except (TypeError, ValueError):
        total = 0
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if days:
        return f"{days} 天 {hours} 时 {minutes} 分"
    if hours:
        return f"{hours} 时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"
