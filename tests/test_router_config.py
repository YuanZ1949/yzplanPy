"""router_admin/config_editor + backup 单测。

覆盖 UCI 往返、危险键拦截、原子写回命令构造、备份的目录内校验与裁剪。
全部离线，不连真机。
"""
import pytest

from modules.router_admin import backup, config_editor
from modules.router_admin.config_editor import (ConfigError, build_read_command,
                                               build_reboot_command,
                                               build_service_restart_command,
                                               build_verify_command,
                                               build_write_command,
                                               find_dangerous_changes,
                                               has_blocking_issue, parse_uci,
                                               serialize_uci)

REAL_NETWORK = """\
config interface 'loopback'
\toption proto 'static'
\toption ipaddr '127.0.0.1'
\toption netmask '255.0.0.0'

config interface 'lan'
\toption type 'bridge'
\toption ifname 'eth1'
\toption proto 'static'
\toption ipaddr '192.168.2.1'
\toption netmask '255.255.255.0'

# 注释行
config route
\toption interface 'lan'
\toption gateway '192.168.2.2'
"""


# ── UCI 解析 ──────────────────────────────────────────────────────────

def test_parse_uci_groups_by_section_type():
    data = parse_uci(REAL_NETWORK)
    assert set(data) == {"interface", "route"}
    assert set(data["interface"]) == {"loopback", "lan"}


def test_parse_uci_reads_options():
    data = parse_uci(REAL_NETWORK)
    assert data["interface"]["lan"]["ipaddr"] == "192.168.2.1"
    assert data["interface"]["lan"]["netmask"] == "255.255.255.0"


def test_parse_uci_reads_list_values():
    text = "config dhcp 'lan'\n\tlist dns '1.1.1.1'\n\tlist dns '8.8.8.8'\n"
    assert parse_uci(text)["dhcp"]["lan"]["dns"] == ["1.1.1.1", "8.8.8.8"]


def test_parse_uci_synthesises_name_for_unnamed_section():
    data = parse_uci("config rule\n\toption target 'ACCEPT'\n")
    assert "rule#0" in data["rule"]


def test_parse_uci_skips_comments_and_blanks():
    data = parse_uci("# c\n\nconfig rule 'a'\n\toption x '1'\n")
    assert data["rule"]["a"] == {"x": "1"}


def test_parse_uci_handles_empty_input():
    assert parse_uci("") == {}
    assert parse_uci(None) == {}


# ── UCI 往返 ──────────────────────────────────────────────────────────

def test_serialize_parse_roundtrip_preserves_sections():
    original = parse_uci(REAL_NETWORK)
    assert parse_uci(serialize_uci(original)) == original


def test_serialize_parse_roundtrip_preserves_lists():
    original = parse_uci("config dhcp 'lan'\n\tlist dns '1.1.1.1'\n\tlist dns '8.8.8.8'\n")
    assert parse_uci(serialize_uci(original)) == original


def test_serialize_emits_list_keyword_for_lists():
    out = serialize_uci({"dhcp": {"lan": {"dns": ["1.1.1.1", "8.8.8.8"]}}})
    assert "\tlist dns '1.1.1.1'" in out
    assert "\tlist dns '8.8.8.8'" in out


def test_serialize_handles_empty():
    assert serialize_uci({}) == ""
    assert serialize_uci(None) == ""


# ── 危险键拦截 ────────────────────────────────────────────────────────

def _network_with_lan_ip(ip):
    return parse_uci(REAL_NETWORK.replace("'192.168.2.1'", f"'{ip}'"))


def test_changing_lan_ip_outside_subnet_is_blocked():
    issues = find_dangerous_changes(
        "network", _network_with_lan_ip("192.168.2.1"),
        _network_with_lan_ip("10.0.0.1"), current_lan_ip="192.168.2.1")
    assert has_blocking_issue(issues) is True


def test_changing_lan_ip_within_subnet_is_warn_only():
    issues = find_dangerous_changes(
        "network", _network_with_lan_ip("192.168.2.1"),
        _network_with_lan_ip("192.168.2.99"), current_lan_ip="192.168.2.1")
    assert has_blocking_issue(issues) is False
    assert any(i["level"] == "warn" for i in issues)


def test_tightening_firewall_input_is_blocked():
    old = parse_uci("config zone 'lan'\n\toption input 'ACCEPT'\n")
    new = parse_uci("config zone 'lan'\n\toption input 'REJECT'\n")
    issues = find_dangerous_changes("firewall", old, new)
    assert has_blocking_issue(issues) is True


def test_tightening_firewall_from_non_accept_is_allowed():
    old = parse_uci("config zone 'lan'\n\toption input 'REJECT'\n")
    new = parse_uci("config zone 'lan'\n\toption input 'DROP'\n")
    assert has_blocking_issue(find_dangerous_changes("firewall", old, new)) is False


def test_enabling_wireless_is_warn_only():
    old = parse_uci("config wifi-device 'radio0'\n\toption disabled '1'\n")
    new = parse_uci("config wifi-device 'radio0'\n\toption disabled '0'\n")
    issues = find_dangerous_changes("wireless", old, new)
    assert has_blocking_issue(issues) is False
    assert any(i["level"] == "warn" for i in issues)


def test_disabling_wireless_is_not_flagged():
    old = parse_uci("config wifi-device 'radio0'\n\toption disabled '0'\n")
    new = parse_uci("config wifi-device 'radio0'\n\toption disabled '1'\n")
    assert find_dangerous_changes("wireless", old, new) == []


def test_password_field_is_blocked():
    old = parse_uci("config system 'main'\n\toption password 'old'\n")
    new = parse_uci("config system 'main'\n\toption password 'new'\n")
    assert has_blocking_issue(find_dangerous_changes("system", old, new)) is True


def test_unchanged_values_are_not_flagged():
    data = parse_uci(REAL_NETWORK)
    assert find_dangerous_changes("network", data, data) == []


def test_non_whitelisted_section_is_blocked():
    issues = find_dangerous_changes("shadow", {}, {"passwd": {"root": {"x": "1"}}})
    assert has_blocking_issue(issues) is True


def test_same_subnet_default_is_slash24():
    from modules.router_admin.config_editor import _same_subnet
    assert _same_subnet("192.168.2.99", "192.168.2.1") is True
    assert _same_subnet("192.168.2.99", "192.168.3.1") is False
    assert _same_subnet("192.168.2.1", "10.0.0.1") is False


def test_same_subnet_honours_octet_count():
    from modules.router_admin.config_editor import _same_subnet
    assert _same_subnet("10.1.2.3", "10.9.9.9", octets=1) is True
    assert _same_subnet("10.1.2.3", "10.9.9.9", octets=2) is False
    assert _same_subnet("10.1.2.3", "10.1.2.4", octets=4) is False


def test_same_subnet_rejects_non_ip():
    from modules.router_admin.config_editor import _same_subnet
    assert _same_subnet("dhcp", "192.168.2.1") is False
    assert _same_subnet("192.168.2", "192.168.2.1") is False
    assert _same_subnet("999.1.1.1", "192.168.2.1") is False


def test_same_subnet_clamps_octets():
    from modules.router_admin.config_editor import _same_subnet
    assert _same_subnet("1.2.3.4", "1.2.3.5", octets=99) is False
    assert _same_subnet("1.2.3.4", "1.2.3.4", octets=0) is True


def test_issues_report_key_and_reason():
    issues = find_dangerous_changes("system",
                                    parse_uci("config system 'a'\n\toption password 'x'\n"),
                                    parse_uci("config system 'a'\n\toption password 'y'\n"))
    assert issues[0]["key"] == "system.system.a.password"
    assert issues[0]["reason"]


# ── 命令构造 ──────────────────────────────────────────────────────────

def test_read_command_only_for_whitelisted_section():
    assert build_read_command("network") == "cat /etc/config/network 2>/dev/null"
    with pytest.raises(ConfigError):
        build_read_command("shadow")


def test_write_command_uses_same_dir_temp_then_mv():
    cmd = build_write_command("dhcp", "config dhcp 'lan'\n")
    assert "cat > /etc/config/.dhcp.yzp.tmp" in cmd
    assert "mv /etc/config/.dhcp.yzp.tmp /etc/config/dhcp" in cmd
    assert "YZ_WRITE_OK" in cmd


def test_write_command_appends_trailing_newline():
    cmd = build_write_command("dhcp", "config dhcp 'lan'")
    assert "\nYZPEOF" in cmd


def test_write_command_rejects_reserved_tag():
    with pytest.raises(ConfigError):
        build_write_command("dhcp", "config x 'YZPEOF'")


def test_write_command_rejects_null_byte():
    with pytest.raises(ConfigError):
        build_write_command("dhcp", "config x '\x00'")


def test_write_command_rejects_non_whitelisted_section():
    with pytest.raises(ConfigError):
        build_write_command("shadow", "x")


# 真机（小米 XiaoQiang，BusyBox ash + telnetd）标定：tty 单行输入上限约 500 字节
# （实测发送 493 字节正常、513 字节超时）。超限时 shell 拿不到完整行，
# 命令永远跑不完 → 读侧只会看到 TelnetTimeoutError。
# 多行粘贴不受该限制约束：真机用 build_write_command 的等价命令写入
# 真实 /etc/config/network（1687 字符 / 68 行）后回读逐字一致。
# 因此这里锁的是「**每一行**都要短」，而不是命令总长。
TTY_SINGLE_LINE_LIMIT = 500


def test_write_command_every_line_fits_tty_limit():
    """真实 /etc/config/network 内容（68 行，最长行 71 字符）逐行都在 tty 上限内。"""
    real_network = "\n".join(
        [
            "config interface 'loopback'",
            "\toption device 'lo'",
            "\toption proto 'static'",
            "\toption ipaddr '127.0.0.1'",
            "\toption netmask '255.0.0.0'",
            "",
            "config interface 'lan'",
            "\toption type 'bridge'",
            "\toption proto 'static'",
            "\toption ipaddr '192.168.2.1'",
            "\toption netmask '255.255.255.0'",
            "\toption ip6assign '64'",
            "\toption igmp_snooping '0'",
            "\toption force_link '1'",
            "",
            "config interface 'wan'",
            "\toption proto 'pppoe'",
            "\toption ifname 'eth0'",
            "\toption mtu '1500'",
            "\toption mru '1480'",
            "\toption ipv6 'auto'",
            "\toption special '0'",
            "\toption username 'a-very-long-pppoe-account-name'",
            "\toption password 'secret'",
            "\toption last_succeed '1'",
        ]
    )
    cmd = build_write_command("network", real_network)
    longest = max(len(line) for line in cmd.splitlines())
    assert longest < TTY_SINGLE_LINE_LIMIT, (
        "写回命令存在 %d 字符的行，超过真机 tty 单行上限 %d，写入必然超时"
        % (longest, TTY_SINGLE_LINE_LIMIT)
    )


def test_write_command_mv_line_fits_tty_limit():
    """末行是 mv + echo，短到不可能越界——但白名单节名长度不受控，故显式锁住。"""
    cmd = build_write_command("network", "config interface 'lan'\n")
    for line in cmd.splitlines():
        assert len(line) < TTY_SINGLE_LINE_LIMIT


def test_verify_command_points_at_written_file():
    assert build_verify_command("dhcp").startswith("head -3 /etc/config/dhcp")


def test_reboot_command_syncs_first():
    assert build_reboot_command() == "sync; reboot"


def test_service_restart_command_delegates_to_services():
    assert build_service_restart_command("dnsmasq") == \
        "sh -c '/etc/init.d/dnsmasq restart 2>&1'"


def test_service_restart_command_rejects_injection():
    with pytest.raises(ConfigError):
        build_service_restart_command("a; reboot")


# ── backup ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))


def test_backup_dir_constant_is_set():
    assert backup.MAX_BACKUPS == 20


def test_remote_backup_command_copies_to_tmp():
    cmd = backup.build_remote_backup_command("network")
    assert "cp /etc/config/network /tmp/yzp_bk_network" in cmd


def test_remote_backup_command_rejects_non_whitelisted():
    with pytest.raises(backup.BackupError):
        backup.build_remote_backup_command("shadow")


def test_remote_read_and_cleanup_commands():
    assert "/tmp/yzp_bk_network" in backup.build_remote_read_command("network")
    assert backup.build_remote_cleanup_command("network") == \
        "rm -f /tmp/yzp_bk_network"


def test_save_backup_writes_file():
    path = backup.save_backup("network", "config x 'y'\n", timestamp=0)
    assert path is not None
    assert open(path, encoding="utf-8").read() == "config x 'y'\n"


def test_save_backup_rejects_non_whitelisted():
    with pytest.raises(backup.BackupError):
        backup.save_backup("shadow", "x")


def test_list_backups_sorted_newest_first():
    backup.save_backup("network", "a", timestamp=1000000)
    backup.save_backup("network", "b", timestamp=2000000)
    names = [item["section"] for item in backup.list_backups()]
    assert names == ["network", "network"]
    assert backup.list_backups()[0]["ts"] != backup.list_backups()[1]["ts"]


def test_list_backups_reports_section_and_size():
    backup.save_backup("dhcp", "12345", timestamp=0)
    item = backup.list_backups()[0]
    assert item["section"] == "dhcp"
    assert item["size"] == 5


def test_list_backups_ignores_foreign_files():
    import os
    os.makedirs(backup.BACKUP_DIR, exist_ok=True)
    open(os.path.join(backup.BACKUP_DIR, "notabackup.txt"), "w").close()
    assert backup.list_backups() == []


def test_list_backups_empty_when_dir_missing():
    assert backup.list_backups() == []


def test_read_backup_returns_content():
    path = backup.save_backup("network", "hello", timestamp=0)
    assert backup.read_backup(path) == "hello"


def test_read_backup_rejects_path_outside_dir(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    assert backup.read_backup(str(outside)) is None


def test_read_backup_rejects_traversal(tmp_path):
    assert backup.read_backup(str(tmp_path / ".." / "escape.txt")) is None


def test_read_backup_returns_none_for_missing():
    assert backup.read_backup("") is None


def test_delete_backup_rejects_outside_path(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    assert backup.delete_backup(str(outside)) is False
    assert outside.exists()


def test_delete_backup_removes_file():
    path = backup.save_backup("network", "x", timestamp=0)
    assert backup.delete_backup(path) is True
    assert backup.list_backups() == []


def test_prune_keeps_only_max_backups():
    for i in range(backup.MAX_BACKUPS + 4):
        backup.save_backup("network", "x", timestamp=1000000 + i)
    assert len(backup.list_backups()) == backup.MAX_BACKUPS


def test_format_size():
    assert backup.format_size(512) == "512 B"
    assert backup.format_size(2048) == "2.0 KB"
    assert backup.format_size("bad") == "-"
