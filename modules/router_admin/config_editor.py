"""router_admin/config_editor：/etc/config 的 UCI 解析、编辑、危险键拦截、原子写回。

UCI 语法（OpenWrt 标准）：
    config <type> '<name>'
        option <key> '<value>'
        list <key> '<value>'

写回用「同目录临时文件 + mv」实现原子替换（`/tmp` 与 `/etc` 跨文件系统，
`cp` 不原子）。改之前必须先由 backup.py 备份。
"""
import re

from .connection import is_allowed_config

_CONFIG_RE = re.compile(r"^config\s+(\S+)\s*(?:'([^']*)'|\"([^\"]*)\")?\s*$")
_OPTION_RE = re.compile(r"^option\s+(\S+)\s+'([^']*)'\s*$")
_LIST_RE = re.compile(r"^list\s+(\S+)\s+'([^']*)'\s*$")

#: 原子写回的 heredoc 终止符（内容中若出现会导致截断，写回前会被拒绝）
HEREDOC_TAG = "YZPEOF"

#: 一律拒绝修改的敏感键名片段
SECRET_KEY_PARTS = ("passwd", "password", "secret", "shadow")


class ConfigError(ValueError):
    """配置操作被拒绝或参数非法。"""


def parse_uci(text):
    """UCI 文本 -> {section_type: {section_name: {key: str | list[str]}}}。

    无引号名的 section 用 `<type>#<序号>` 命名，保证可回写。注释与空行丢弃。
    """
    data = {}
    current = None
    counts = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _CONFIG_RE.match(line)
        if match:
            stype = match.group(1)
            name = match.group(2) or match.group(3)
            if not name:
                index = counts.get(stype, 0)
                name = f"{stype}#{index}"
            counts[stype] = counts.get(stype, 0) + 1
            data.setdefault(stype, {})[name] = {}
            current = data[stype][name]
            continue
        if current is None:
            continue
        opt = _OPTION_RE.match(line)
        if opt:
            current[opt.group(1)] = opt.group(2)
            continue
        lst = _LIST_RE.match(line)
        if lst:
            key, value = lst.group(1), lst.group(2)
            if isinstance(current.get(key), list):
                current[key].append(value)
            else:
                current[key] = [value]
    return data


def serialize_uci(data):
    """{section_type: {name: {key: value}}} -> UCI 文本。"""
    lines = []
    for stype in data or {}:
        sections = data[stype] or {}
        for name in sections:
            lines.append(f"config {stype} '{name}'")
            options = sections[name] or {}
            for key in options:
                value = options[key]
                if isinstance(value, list):
                    for item in value:
                        lines.append(f"\tlist {key} '{item}'")
                else:
                    lines.append(f"\toption {key} '{value}'")
            lines.append("")
    return "\n".join(lines)


def _is_ip(text):
    parts = (text or "").split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _same_subnet(a, b, octets=3):
    """粗略同网段判断：前 octets 段相同即视为同段（默认按 /24）。"""
    if not (_is_ip(a) and _is_ip(b)):
        return False
    octets = max(1, min(4, int(octets)))
    return a.split(".")[:octets] == b.split(".")[:octets]


def _check_lan_ip(full, old_value, new_value, current_lan_ip, issues):
    """网关地址规则：跳出当前 LAN 网段会切断本机 telnet，必须 block。"""
    if current_lan_ip and not _same_subnet(str(new_value), current_lan_ip):
        issues.append({
            "level": "block", "key": full,
            "reason": f"新网关 {new_value} 不在当前 LAN {current_lan_ip} 所在网段，"
                      "写入后本机会失联"})
    else:
        issues.append({"level": "warn", "key": full,
                       "reason": f"网关由 {old_value} 改为 {new_value}"})


def _check_firewall_input(full, old_value, new_value, issues):
    """防火墙 input 从 ACCEPT 收紧会让路由器自身失联，必须 block。

    放宽（ACCEPT -> 其他 ACCEPT 系值之外的方向）不拦；只拦「由 ACCEPT 收紧」。
    """
    if str(old_value).upper() == "ACCEPT" and str(new_value).upper() != "ACCEPT":
        issues.append({
            "level": "block", "key": full,
            "reason": "禁止把防火墙 input 从 ACCEPT 收紧，可能导致路由器自身失联"})


def _check_wireless_disabled(full, new_value, issues):
    """启用无线（disabled=0）需二次确认——可能把自己锁在外面。"""
    if str(new_value) in ("0", "false"):
        issues.append({"level": "warn", "key": full,
                       "reason": "将启用无线（disabled=0），确认不会锁死自己"})


def _check_removed_key(section, stype, name, key, old_value, issues):
    """删除既有键的风险评估——删除与赋值同样会改变路由器行为。

    删掉 `network` 里 lan 接口的 `ipaddr`，效果与把它改成非法地址一样：
    路由器失去 LAN 地址，本机 telnet 立即失联。这条路径不能因为「改动
    检测只扫新文本」而漏掉。
    """
    full = f"{section}.{stype}.{name}.{key}"
    lowered = key.lower()
    if any(part in lowered for part in SECRET_KEY_PARTS):
        issues.append({"level": "block", "key": full,
                       "reason": "拒绝删除口令/密钥类字段"})
    elif section == "network" and key == "ipaddr":
        issues.append({
            "level": "block", "key": full,
            "reason": "删除网关地址会切断本机 telnet，写入后本机会失联"})
    elif key == "input" and stype == "zone":
        issues.append({
            "level": "block", "key": full,
            "reason": "删除防火墙 input 规则会切断本机对路由器的访问"})
    else:
        issues.append({"level": "warn", "key": full,
                       "reason": f"将删除 {key}（原值 {old_value}）"})


def find_dangerous_changes(section, old, new, *, current_lan_ip=None):
    """比对某个配置文件的改前改后，返回 [{level, key, reason}]。

    section 是**文件名**（network/dhcp/fireless/...），old/new 是该文件
    parse_uci 的结果 {section_type: {name: {key: value}}}。规则同时依赖
    文件名与文件内的 section type（如 network 文件里的 `interface` 段的
    `ipaddr`），因此按 (文件, 内层 type, 键) 三元组分派。

    level="block" 必须拒绝写入；level="warn" 需 UI 二次确认。
    非白名单文件一律 block。
    """
    issues = []
    if not is_allowed_config(section):
        issues.append({"level": "block", "key": section,
                       "reason": f"{section} 不在允许编辑的配置白名单内"})
        return issues

    old_all = old or {}
    new_all = new or {}
    for stype in sorted(set(old_all) | set(new_all)):
        old_sections = old_all.get(stype) or {}
        new_sections = new_all.get(stype) or {}
        for name in sorted(set(old_sections) | set(new_sections)):
            old_opts = old_sections.get(name) or {}
            new_opts = new_sections.get(name) or {}
            for key, new_value in (new_opts or {}).items():
                lowered = key.lower()
                full = f"{section}.{stype}.{name}.{key}"
                if any(part in lowered for part in SECRET_KEY_PARTS):
                    issues.append({"level": "block", "key": full,
                                   "reason": "拒绝修改口令/密钥类字段"})
                    continue
                old_value = old_opts.get(key)
                if old_value == new_value:
                    continue
                if section == "network" and key == "ipaddr":
                    _check_lan_ip(full, old_value, new_value, current_lan_ip, issues)
                elif key == "input" and stype == "zone":
                    _check_firewall_input(full, old_value, new_value, issues)
                elif section == "wireless" and key == "disabled":
                    _check_wireless_disabled(full, new_value, issues)
            for key, old_value in old_opts.items():
                if key not in new_opts:
                    _check_removed_key(section, stype, name, key,
                                       old_value, issues)
    return issues


def has_blocking_issue(issues):
    return any(i.get("level") == "block" for i in issues or [])


def build_read_command(section):
    """读一个白名单配置文件的命令。"""
    if not is_allowed_config(section):
        raise ConfigError(f"{section!r} 不在白名单内")
    return f"cat /etc/config/{section} 2>/dev/null"


#: 写回命令的**单行**安全上限（字符）。
#:
#: 真机（小米 XiaoQiang，BusyBox ash + telnetd）标定：tty 的规范输入行缓冲约 500
#: 字节，**每一行**超限就会被截断——shell 拿不到完整的一行，命令永远跑不完，读侧
#: 只会等到 `TelnetTimeoutError`（实测一行 493 字节可过、513 字节超时）。约束对象是
#: **行**而不是命令总长：heredoc 写回是多行命令，真机写入 1687 字符 / 68 行后回读
#: 逐字一致（见 tests/test_router_config.py 的标定）。留出 `; echo; echo __YZP_xxxxxxxx__`
#: 与安全余量后取 400。
MAX_TTY_LINE = 400


def build_write_command(section, content):
    """原子写回：同目录临时文件 + mv 替换。任一行超 `MAX_TTY_LINE` 直接报错。"""
    if not is_allowed_config(section):
        raise ConfigError(f"{section!r} 不在白名单内")
    body = str(content or "")
    if not body.endswith("\n"):
        body += "\n"
    if HEREDOC_TAG in body:
        raise ConfigError("配置内容包含保留标记，无法安全写回")
    if "\x00" in body:
        raise ConfigError("配置内容含空字符，无法写回")
    command = (f"cat > /etc/config/.{section}.yzp.tmp <<'{HEREDOC_TAG}'\n"
               f"{body}{HEREDOC_TAG}\n"
               f"mv /etc/config/.{section}.yzp.tmp /etc/config/{section} && echo YZ_WRITE_OK")
    _reject_long_lines(command)
    return command


def _reject_long_lines(command):
    """任一行超 `MAX_TTY_LINE` 就抛错，而不是让 tty 把它截断后写出坏配置。"""
    for index, line in enumerate(command.split("\n"), 1):
        if len(line) > MAX_TTY_LINE:
            raise ConfigError(
                f"写回命令第 {index} 行有 {len(line)} 字符，超过 tty 单行上限 "
                f"{MAX_TTY_LINE}（真机上会被截断）")


def build_verify_command(section):
    """写回后回读校验。"""
    if not is_allowed_config(section):
        raise ConfigError(f"{section!r} 不在白名单内")
    return f"head -3 /etc/config/{section} 2>/dev/null"


def build_reboot_command():
    """整系统重启。先 sync 落盘。"""
    return "sync; reboot"


def build_service_restart_command(service_name):
    """重启单个服务使配置生效（不重启整机）。"""
    from .services import ServiceError, build_action_command
    try:
        return build_action_command(service_name, "restart")
    except ServiceError as exc:
        raise ConfigError(str(exc)) from exc
