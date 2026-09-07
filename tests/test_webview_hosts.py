import os
import sys

from modules.webview_control import (
    blocked_host,
    kill_host_webview,
    load_blocked_exes,
    save_blocked_exes,
    scan_hosts,
)
from modules.webview_control.config import HOST_LOG_MAX, load_host_log, save_host_log
from modules.webview_control.module import Module


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


# ── 拦截记录（host_log） ──────────────────────────────────────────────

class _FakeContext:
    def __init__(self, config):
        self.config = config


def test_host_log_roundtrip():
    cfg = _FakeConfig()
    entries = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-02 00:00:00",
         "status": "pending"},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B",
         "first_seen": "2026-01-01 00:00:00", "last_seen": "2026-01-03 00:00:00",
         "status": "blocked"},
    ]
    save_host_log(cfg, entries)
    loaded = load_host_log(cfg)
    # save 按 last_seen 排序，比较内容而非顺序
    assert sorted(loaded, key=lambda e: e["exe"]) == sorted(entries, key=lambda e: e["exe"])


def test_host_log_missing_or_corrupt_returns_empty():
    cfg = _FakeConfig()
    assert load_host_log(cfg) == []
    cfg.data["webview"] = {"host_log": "not-a-list"}
    assert load_host_log(cfg) == []
    cfg.data["webview"] = {"host_log": [{"no_exe": 1}, "junk", None]}
    assert load_host_log(cfg) == []


def test_host_log_caps_at_max_evicts_oldest():
    cfg = _FakeConfig()
    entries = [
        {"exe": _norm(fr"C:\Apps\H{i}.exe"), "name": f"H{i}",
         "first_seen": f"2026-01-01 00:00:{i:03d}", "last_seen": f"2026-01-01 00:00:{i:03d}",
         "status": "pending"}
        for i in range(HOST_LOG_MAX + 50)
    ]
    save_host_log(cfg, entries)
    loaded = load_host_log(cfg)
    assert len(loaded) == HOST_LOG_MAX
    # 保留 last_seen 最新的（i=249 最新）
    assert loaded[0]["exe"] == _norm(r"C:\Apps\H249.exe")
    assert loaded[-1]["exe"] == _norm(r"C:\Apps\H50.exe")


def test_monitor_records_new_pending_host():
    cfg = _FakeConfig()
    mod = Module(_FakeContext(cfg))
    fake_hosts = [{"exe": _norm(r"C:\Apps\New.exe"), "name": "New", "blocked": False}]
    mod._record_hosts(fake_hosts)
    assert len(mod.host_log) == 1
    ent = mod.host_log[0]
    assert ent["exe"] == _norm(r"C:\Apps\New.exe")
    assert ent["status"] == "pending"
    assert ent["first_seen"] == ent["last_seen"]
    # 已持久化
    assert load_host_log(cfg)[0]["status"] == "pending"


def test_monitor_updates_last_seen_and_marks_blocked():
    cfg = _FakeConfig()
    mod = Module(_FakeContext(cfg))
    mod.host_log = [{"exe": _norm(r"C:\Apps\New.exe"), "name": "New",
                     "first_seen": "old", "last_seen": "old", "status": "pending"}]
    fake_hosts = [{"exe": _norm(r"C:\Apps\New.exe"), "name": "New", "blocked": True}]
    mod._record_hosts(fake_hosts)
    ent = mod.host_log[0]
    assert ent["status"] == "blocked"
    assert ent["last_seen"] != "old"
    assert load_host_log(cfg)[0]["status"] == "blocked"


def test_set_host_handler_allow_block_forget():
    cfg = _FakeConfig()
    mod = Module(_FakeContext(cfg))
    exe = _norm(r"C:\Apps\X.exe")
    mod.host_log = [{"exe": exe, "name": "X",
                     "first_seen": "t0", "last_seen": "t0", "status": "pending"}]

    mod.set_host_handler(exe, "block")
    assert exe in mod.blocked
    assert mod.host_log[0]["status"] == "blocked"
    assert load_host_log(cfg)[0]["status"] == "blocked"

    mod.set_host_handler(exe, "allow")
    assert exe not in mod.blocked
    assert mod.host_log[0]["status"] == "allowed"
    assert load_host_log(cfg)[0]["status"] == "allowed"

    mod.set_host_handler(exe, "forget")
    assert mod.host_log == []
    assert load_host_log(cfg) == []
    assert exe not in mod.blocked


def test_set_host_handler_unknown_action_raises():
    cfg = _FakeConfig()
    mod = Module(_FakeContext(cfg))
    try:
        mod.set_host_handler(_norm(r"C:\Apps\X.exe"), "nuke")
    except ValueError:
        return
    raise AssertionError("未知动作应抛 ValueError")
