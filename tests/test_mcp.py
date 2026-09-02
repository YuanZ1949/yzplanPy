"""MCP 服务器工具回归测试。

覆盖 mcp_server 所有工具处理器，确保不因缺导入/缺字段而抛未捕获异常。
曾出现 bug：rss_recent 未导入 sqlite3 导致 NameError → HTTP 500。
"""

import sys
sys.path.insert(0, ".")

import time

import pytest


@pytest.fixture(scope="module")
def mcp():
    import mcp_server as m
    return m


def _call(mcp, name, args):
    tool = mcp._TOOL_BY_NAME[name]
    return tool["handler"](args)


def test_all_tools_listed(mcp):
    names = {t["name"] for t in mcp.TOOLS}
    expected = {"todo_list", "todo_add", "todo_update", "todo_delete", "todo_stats",
                "system_info", "system_resources", "logs_get", "logs_clear",
                "rss_list", "rss_add", "rss_update", "rss_delete", "rss_recent",
                "gui_notify", "perf_threads", "perf_stats", "perf_profile",
                "perf_enable", "perf_reset"}
    assert expected <= names


def test_todo_stats(mcp):
    s = _call(mcp, "todo_stats", {})
    assert {"total", "done", "pending"} <= set(s)


def test_todo_crud_roundtrip(mcp):
    created = _call(mcp, "todo_add", {"title": "__mcp_test__", "priority": 1})
    assert isinstance(created, list) and created
    tid = created[0]["id"]
    try:
        updated = _call(mcp, "todo_update", {"id": tid, "done": True})
        assert updated[0]["done"] == 1
        found = _call(mcp, "todo_list", {"keyword": "__mcp_test__"})
        assert len(found) >= 1
    finally:
        _call(mcp, "todo_delete", {"id": tid})
    gone = _call(mcp, "todo_list", {"keyword": "__mcp_test__"})
    assert all(t["id"] != tid for t in gone)


def test_todo_update_missing_id_raises_valueerror(mcp):
    with pytest.raises(ValueError):
        _call(mcp, "todo_update", {"id": 99999999})


def test_system_tools(mcp):
    si = _call(mcp, "system_info", {})
    assert si
    res = _call(mcp, "system_resources", {})
    assert {"cpu_percent", "memory_percent"} <= set(res)


def test_logs_tools(mcp):
    logs = _call(mcp, "logs_get", {})
    assert isinstance(logs, list)
    cleared = _call(mcp, "logs_clear", {})
    assert cleared.get("cleared") is True


def test_rss_recent_no_crash(mcp):
    # 回归：曾因缺少 sqlite3 导入抛出 NameError
    recent = _call(mcp, "rss_recent", {"limit": 5})
    assert isinstance(recent, list)


def test_rss_crud_roundtrip(mcp):
    name = "__mcp_test_feed__"
    added = _call(mcp, "rss_add", {"name": name, "url": "https://example.com/rss"})
    fid = added["id"]
    try:
        found = _call(mcp, "rss_list", {})
        assert any(f["id"] == fid for f in found)
        upd = _call(mcp, "rss_update", {"id": fid, "tag": "test"})
        assert upd["tag"] == "test"
    finally:
        _call(mcp, "rss_delete", {"id": fid})
    assert not any(f["id"] == fid for f in _call(mcp, "rss_list", {}))


def test_gui_notify(mcp):
    import json
    import os
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    before = set(os.listdir(inbox))
    r = _call(mcp, "gui_notify", {"title": "t", "message": "m", "level": "info"})
    assert r.get("queued") is True
    # 清理产生的通知文件
    after = set(os.listdir(inbox))
    for name in after - before:
        try:
            os.remove(os.path.join(inbox, name))
        except OSError:
            pass


def test_handle_message_initialize_and_tools(mcp):
    init = mcp.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "yzplan-mcp"
    tl = mcp.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(tl["result"]["tools"]) == len(mcp.TOOLS)
    # tools/list 必须剥离 handler（否则 JSON 序列化崩溃）
    assert all("handler" not in t for t in tl["result"]["tools"])


def test_perf_tools(mcp):
    # 诊断工具：线程栈快照/耗时统计/采样器/开关/清空 都能正常调用
    th = _call(mcp, "perf_threads", {})
    assert isinstance(th["threads"], list)
    assert any(t.get("stack") for t in th["threads"])
    st = _call(mcp, "perf_stats", {})
    assert {"enabled", "uptime_s", "rows"} <= set(st)
    pr = _call(mcp, "perf_profile", {})
    assert "running" in pr and isinstance(pr.get("functions"), list)
    en = _call(mcp, "perf_enable", {"on": False})
    assert en["enabled"] is False
    en2 = _call(mcp, "perf_enable", {"on": True})
    assert en2["enabled"] is True
    rs = _call(mcp, "perf_reset", {})
    assert rs["reset"] is True


def test_profiler_hook_no_freeze():
    """回归：函数采样器钩子必须返回 None 并使用独立锁，否则在 stats() 迭代期间
    递归触发钩子 + 共享不可重入锁死锁，导致主线程卡死。"""
    import threading
    import core.perf as perf
    perf.reset()
    done = [False]
    freeze = [False]

    def watchdog():
        time.sleep(5)
        if not done[0]:
            freeze[0] = True
            raise SystemExit(2)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        perf.profile_start()
        try:
            # 复现线上卡死场景：采样器开启的同时主线程反复调用 stats()
            for _ in range(50000):
                perf.stats()
        finally:
            perf.profile_stop()
        assert freeze[0] is False
        assert perf._profiler_enabled is False
    finally:
        done[0] = True
        if perf._profiler_enabled:
            perf.profile_stop()


def test_handle_message_tools_call_and_unknown(mcp):
    r = mcp.handle_message({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "todo_stats", "arguments": {}}})
    assert r["result"]["isError"] is False
    bad = mcp.handle_message({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "no_such_tool", "arguments": {}}})
    assert bad["error"]["code"] == -32602
    # 工具内部异常也应转为 JSON-RPC 错误而非抛出
    missing = mcp.handle_message({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "todo_update", "arguments": {"id": 99999999}}})
    assert missing["error"]["code"] in (-32602, -32603)
