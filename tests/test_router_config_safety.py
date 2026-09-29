"""config_editor 删除路径的安全回归测试。

`find_dangerous_changes` 的改动检测原本只遍历新文本里**存在**的键，
因此「删除某个既有键」完全不经过检查。而删掉 `network` 里 `lan` 接口的
`ipaddr`，效果与把它改成非法地址一样——路由器失去 LAN 地址，
本机 telnet 立即失联。这类操作必须与赋值一样被拦。
"""
import pytest

from modules.router_admin.config_editor import (
    find_dangerous_changes,
    has_blocking_issue,
)

OLD = {
    "interface": {
        "lan": {
            "proto": "static",
            "ipaddr": "192.168.2.1",
            "netmask": "255.255.255.0",
        },
        "wan": {
            "proto": "pppoe",
        },
    },
    "route": {
        "lan": {
            "interface": "lan",
            "target": "192.168.2.0",
        },
    },
}


def _levels(issues, key_suffix):
    return [i["level"] for i in issues if i["key"].endswith(key_suffix)]


def test_removing_lan_ipaddr_is_blocked():
    """删掉 lan 的 ipaddr 等同于抹掉 LAN 地址，必须 block。"""
    new = {
        "interface": {
            "lan": {"proto": "static", "netmask": "255.255.255.0"},
            "wan": {"proto": "pppoe"},
        },
        "route": {
            "lan": {"interface": "lan", "target": "192.168.2.0"},
        },
    }
    issues = find_dangerous_changes(
        "network", OLD, new, current_lan_ip="192.168.2.1")
    assert "block" in _levels(issues, "lan.ipaddr")
    assert has_blocking_issue(issues)


def test_removing_whole_lan_interface_is_blocked():
    """整个 interface lan 段被删掉，里面的 ipaddr 也算被删。"""
    new = {
        "interface": {"wan": {"proto": "pppoe"}},
        "route": {"lan": {"interface": "lan", "target": "192.168.2.0"}},
    }
    issues = find_dangerous_changes(
        "network", OLD, new, current_lan_ip="192.168.2.1")
    assert "block" in _levels(issues, "lan.ipaddr")
    assert has_blocking_issue(issues)


def test_removing_firewall_input_is_blocked():
    """删掉 zone 的 input 规则会切断本机对路由器的访问。"""
    old = {"zone": {"lan": {"name": "lan", "input": "ACCEPT"}}}
    new = {"zone": {"lan": {"name": "lan"}}}
    issues = find_dangerous_changes("firewall", old, new)
    assert "block" in _levels(issues, "lan.input")
    assert has_blocking_issue(issues)


def test_removing_secret_key_is_blocked():
    old = {"system": {"root": {"password": "$1$abc$def"}}}
    new = {"system": {"root": {}}}
    issues = find_dangerous_changes("system", old, new)
    assert "block" in _levels(issues, "root.password")


def test_unchanged_content_produces_no_issues():
    """回填原样保存不应报任何问题（删除检测不能误伤无改动场景）。"""
    issues = find_dangerous_changes(
        "network", OLD, OLD, current_lan_ip="192.168.2.1")
    assert issues == []


def test_added_key_still_reports_as_before():
    """新增键走原有赋值路径，行为不变。"""
    new = {
        "interface": {
            "lan": {
                "proto": "static",
                "ipaddr": "192.168.2.1",
                "netmask": "255.255.255.0",
                "mtu": "1500",
            },
            "wan": {"proto": "pppoe"},
        },
        "route": {
            "lan": {"interface": "lan", "target": "192.168.2.0"},
        },
    }
    issues = find_dangerous_changes(
        "network", OLD, new, current_lan_ip="192.168.2.1")
    # ipaddr 未变，不应触发网关检查；mtu 是新增但无害
    assert "block" not in _levels(issues, "lan.ipaddr")
    assert not has_blocking_issue(issues)


def test_non_whitelisted_section_still_blocks():
    issues = find_dangerous_changes("passwd", {}, {"system": {}})
    assert has_blocking_issue(issues)


def test_empty_new_keeps_old_keys_visible_as_removal():
    """new 为空（清空整个文件）时，所有旧键都算被删。"""
    issues = find_dangerous_changes(
        "network", OLD, {}, current_lan_ip="192.168.2.1")
    assert "block" in _levels(issues, "lan.ipaddr")
    assert has_blocking_issue(issues)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
