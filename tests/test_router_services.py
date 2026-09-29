"""router_admin/services 单测：服务名白名单（命令注入防线）与命令构造。

**不连真机**：全部是纯字符串与解析函数的断言。
"""
import pytest

from modules.router_admin import services
from modules.router_admin.services import (DANGEROUS_SERVICES, ServiceError,
                                          build_action_command,
                                          build_autostart_command,
                                          is_dangerous, is_valid_service_name,
                                          parse_autostart, parse_service_list)


# ── 名字白名单（安全关键） ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["network", "dnsmasq", "hostapd",
                                  "syslog-ng", "a.b", "a_b", "A1"])
def test_valid_service_names_accepted(name):
    assert is_valid_service_name(name) is True


@pytest.mark.parametrize("name", [
    "../../etc/passwd", "a;reboot", "a b", "a b", "a&&b", "a|b",
    "a`b`", "a$(b)", "a\nb", "", None, "a'b", 'a"b', "a>b", "a<b",
    "/etc/init.d", "a\tb",
])
def test_invalid_service_names_rejected(name):
    assert is_valid_service_name(name) is False


def test_dot_and_dotdot_rejected():
    assert is_valid_service_name(".") is True   # 正则层面通过
    with pytest.raises(ServiceError):
        build_action_command(".", "start")
    with pytest.raises(ServiceError):
        build_action_command("..", "start")


# ── 动作白名单 ────────────────────────────────────────────────────────

def test_action_command_for_valid_action():
    assert build_action_command("dnsmasq", "restart") == \
        "sh -c '/etc/init.d/dnsmasq restart 2>&1'"


def test_action_command_lowercases_action():
    assert "stop 2>&1" in build_action_command("x", "STOP")


def test_action_command_rejects_injection_name():
    with pytest.raises(ServiceError):
        build_action_command("dnsmasq; reboot", "start")


def test_action_command_rejects_invalid_action():
    with pytest.raises(ServiceError):
        build_action_command("dnsmasq", "destroy")


def test_action_command_rejects_empty_name():
    with pytest.raises(ServiceError):
        build_action_command("", "start")


# ── 危险服务 ──────────────────────────────────────────────────────────

def test_dangerous_services_detected():
    for name in ("network", "firewall", "dnsmasq", "netifd", "hostapd"):
        assert is_dangerous(name) is True
    assert is_dangerous("NETWORK") is True
    assert is_dangerous("someapp") is False


def test_dangerous_set_is_non_empty():
    assert len(DANGEROUS_SERVICES) >= 5


# ── 列表解析 ──────────────────────────────────────────────────────────

def test_parse_service_list_filters_invalid_names():
    text = "network\ndnsmasq\na;b\n\n  hostapd  \n../evil\n"
    assert parse_service_list(text) == ["network", "dnsmasq", "hostapd"]


def test_parse_service_list_dedupes_preserving_order():
    assert parse_service_list("b\na\nb\n") == ["b", "a"]


def test_parse_service_list_handles_empty_input():
    assert parse_service_list("") == []
    assert parse_service_list(None) == []


def test_list_command_points_at_init_d():
    assert "/etc/init.d" in services.list_command()


# ── 自启动状态 ────────────────────────────────────────────────────────

def test_autostart_command_quotes_names():
    cmd = build_autostart_command(["dnsmasq", "network"])
    assert '"dnsmasq" "network"' in cmd
    assert "enabled" in cmd


def test_autostart_command_filters_invalid_names():
    cmd = build_autostart_command(["ok", "a;b"])
    assert '"ok"' in cmd
    assert "a;b" not in cmd


def test_autostart_command_empty_for_all_invalid():
    assert build_autostart_command(["a;b"]) == ""
    assert build_autostart_command([]) == ""


def test_parse_autostart():
    text = "dnsmasq 1\nnetwork 0\nbogus 1\ngarbage\n"
    assert parse_autostart(text) == {"dnsmasq": True, "network": False,
                                     "bogus": True}


def test_parse_autostart_handles_empty():
    assert parse_autostart("") == {}
