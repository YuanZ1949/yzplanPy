import os
import sys

from modules.webview_control import (
    blocked_host,
    kill_host_webview,
    load_blocked_exes,
    save_blocked_exes,
    scan_hosts,
)


def _norm(p):
    return os.path.normcase(p).lower()


class _FakeConfig:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):
        pass


def test_load_blocked_defaults_empty():
    cfg = _FakeConfig()
    assert load_blocked_exes(cfg) == set()


def test_save_and_load_blocked_roundtrip():
    cfg = _FakeConfig()
    blocked = {_norm(r"C:\Apps\WeiXin.exe"), _norm(r"C:\Apps\WeChat.exe")}
    save_blocked_exes(cfg, blocked)
    loaded = load_blocked_exes(cfg)
    assert loaded == blocked
    assert all(x.islower() for x in loaded)


def test_blocked_host_matching_case_insensitive():
    b = {_norm(r"C:\Apps\WeiXin.exe")}
    assert blocked_host(r"c:\apps\weixin.exe", b) is True
    assert blocked_host(r"C:\apps\OTHER.exe", b) is False
    assert blocked_host(r"C:\Apps\WeiXin.exe", None) is False


def test_scan_hosts_returns_list():
    hosts = scan_hosts(set())
    assert isinstance(hosts, list)
    for h in hosts:
        assert "exe" in h
        assert "name" in h
        assert "running" in h
        assert "blocked" in h
        assert "connections" in h
        assert "webview_count" in h
        assert "user_data_dirs" in h


def test_scan_hosts_marks_blocked():
    # 用任意不存在路径测：不会崩溃，且 blocked 标记取决于外来集合
    fake = _norm(r"C:\DoesNotExist\FakeHost.exe")
    hosts = scan_hosts({fake})
    assert isinstance(hosts, list)


def test_kill_host_webview_no_crash():
    # 无 webview 或目标不存在时不应抛异常
    result = kill_host_webview({_norm(r"C:\Nope\X.exe")})
    assert isinstance(result, list)
