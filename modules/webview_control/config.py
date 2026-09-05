"""webview_control - blocked hosts config persistence."""
import os

def load_blocked_exes(config):
    """从 config 读取被拦截的宿主程序 exe 列表。"""
    raw = config.get("webview.blocked_hosts", [])
    if isinstance(raw, str):
        raw = [raw]
    return set(os.path.normcase(x).lower() for x in (raw or []) if x)


def save_blocked_exes(config, blocked):
    config.set("webview.blocked_hosts", sorted(blocked))
