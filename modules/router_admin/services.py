"""router_admin/services：/etc/init.d 服务列举与启停命令构造。

安全要点：服务名必须过白名单正则，杜绝 `../../etc/passwd`、`a;reboot` 之类
的命令注入；危险服务（会切断自身连接）在 UI 侧标红并要求二次确认。
"""
import re

#: 合法服务名：字母数字下划线点连字符，无任何 shell 元字符
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

#: ANSI 终端转义序列（`\x1b[1;32m` … `\x1b[0m`）。本机 BusyBox 的 `ls` 在 tty 下
#: 会输出颜色码，色码混进文件名会让 SERVICE_NAME_RE 校验全部失败。
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

VALID_ACTIONS = ("start", "stop", "restart", "reload")

#: 会影响自身连通性的服务 —— UI 需二次确认
DANGEROUS_SERVICES = frozenset({
    "network", "firewall", "dnsmasq", "netifd", "pppd", "odhcpd",
    "uhttpd", "hostapd", "wpad", "sysntpd", "odhcp6c",
})

SERVICE_DIR = "/etc/init.d"


class ServiceError(ValueError):
    """服务名或动作非法。"""


def is_valid_service_name(name):
    return bool(name) and bool(SERVICE_NAME_RE.match(name))


def is_dangerous(name):
    return (name or "").strip().lower() in DANGEROUS_SERVICES


def parse_service_list(text):
    """解析服务目录列表输出，返回合法服务名列表（去重、保序）。

    先整体剥离 ANSI 颜色码再逐行校验 —— 本机 BusyBox 的 `ls` 在 tty 下会给每个
    文件名套 `\\x1b[1;32m` / `\\x1b[0m`，不剥离的话 `SERVICE_NAME_RE` 会把它们
    全部判为非法（真机实测 60+ 个服务解析出 0 个）。色码剥离是**第二道防线**：
    即使命令侧换了写法、别的固件/别的调用方仍给了带色码的文本，也能解析。
    """
    out = []
    seen = set()
    for line in ANSI_RE.sub("", text or "").splitlines():
        name = line.strip()
        if not name or not is_valid_service_name(name):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def list_command():
    """列出全部服务。

    用 shell 的 glob 展开 + `basename` 而**不用 `ls`**：本机 BusyBox 的 `ls` 在 tty
    下强制输出 ANSI 颜色码（且不认 `--color=never`），靠 `2>/dev/null` 屏蔽不掉。
    `for` 循环与 `basename` 在 BusyBox ash 上均可用。
    旧写法（已弃用，保留备查）：`ls -1 /etc/init.d 2>/dev/null`
    """
    return f"for f in {SERVICE_DIR}/*; do basename $f; done 2>/dev/null"


def build_autostart_command(names):
    """批量查询服务的自启动状态。

    OpenWrt 的 `<name> enabled` 退出码 0 = 开机自启。非零一律记为 0。
    返回形如 `name 1` / `name 0` 的行，便于解析。
    """
    safe = [n for n in (names or []) if is_valid_service_name(n)]
    if not safe:
        return ""
    body = " ".join(f'"{n}"' for n in safe)
    return (f'for n in {body}; do '
            f'{SERVICE_DIR}/$n enabled >/dev/null 2>&1 && echo "$n 1" || echo "$n 0"; '
            f'done')


def parse_autostart(text):
    """解析自启动查询输出 -> {name: bool}。"""
    out = {}
    for line in (text or "").splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and is_valid_service_name(parts[0]):
            out[parts[0]] = parts[1].strip() == "1"
    return out


def build_action_command(name, action):
    """构造 `sh -c '/etc/init.d/<name> <action>'`。非法输入抛 ServiceError。"""
    name = (name or "").strip()
    if not is_valid_service_name(name):
        raise ServiceError(f"非法服务名：{name!r}")
    if name in (".", ".."):
        raise ServiceError(f"非法服务名：{name!r}")
    action = (action or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise ServiceError(f"非法动作：{action!r}")
    return f"sh -c '{SERVICE_DIR}/{name} {action} 2>&1'"
