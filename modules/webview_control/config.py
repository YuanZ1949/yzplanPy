"""webview_control - blocked hosts config persistence."""
import os

HOST_LOG_MAX = 200


def load_blocked_exes(config):
    """从 config 读取被拦截的宿主程序 exe 列表。"""
    raw = config.get("webview.blocked_hosts", [])
    if isinstance(raw, str):
        raw = [raw]
    return set(os.path.normcase(x).lower() for x in (raw or []) if x)


def save_blocked_exes(config, blocked):
    config.set("webview.blocked_hosts", sorted(blocked))


def load_host_log(config):
    """从 config 读取宿主拦截记录列表；缺失/损坏时返回空列表不崩溃。

    每条记录: {exe, name, first_seen, last_seen, status}
    status ∈ pending/allowed/blocked
    """
    raw = config.get("webview.host_log", [])
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        exe = item.get("exe")
        if not exe:
            continue
        exe_n = os.path.normcase(exe).lower()
        status = item.get("status", "pending")
        if status not in ("pending", "allowed", "blocked"):
            status = "pending"
        entries.append({
            "exe": exe_n,
            "name": item.get("name") or (os.path.basename(exe_n).replace(".exe", "") or exe_n),
            "first_seen": item.get("first_seen", ""),
            "last_seen": item.get("last_seen", ""),
            "status": status,
        })
    return entries


def save_host_log(config, entries):
    """保存宿主拦截记录，按 last_seen 淘汰最旧，上限 HOST_LOG_MAX 条。"""
    capped = sorted(entries, key=lambda e: e.get("last_seen", ""), reverse=True)[:HOST_LOG_MAX]
    config.set("webview.host_log", capped)
