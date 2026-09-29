"""proxy_ctrl/store：扫描历史与记忆的代理 URL 落盘。

单文件 JSON（<DATA_DIR>/proxy_ctrl/history.json），保留最近 20 次扫描。
STORE_PATH 在每次调用时读取模块全局，测试可 monkeypatch 到 tmp_path。
"""
import json
import os

from core.constants import DATA_DIR

STORE_PATH = os.path.join(DATA_DIR, "proxy_ctrl", "history.json")
EXPORT_DIR = os.path.join(DATA_DIR, "proxy_ctrl", "exports")

MAX_SCANS = 20
_NOT_SET = ""


def _empty_state():
    return {"last_proxy_url": _NOT_SET, "scans": []}


def load():
    """读状态；文件缺失或损坏时返回空状态（不抛异常）。"""
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    state = _empty_state()
    url = data.get("last_proxy_url")
    state["last_proxy_url"] = str(url) if isinstance(url, str) else _NOT_SET
    scans = data.get("scans")
    if isinstance(scans, list):
        state["scans"] = [s for s in scans if isinstance(s, dict)][-MAX_SCANS:]
    return state


def save(state):
    """写状态。返回 True 成功 / False 失败。"""
    try:
        os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
    except (OSError, ValueError):
        # ValueError: 路径含空字符等非法字符时 os.makedirs 抛的是它而非 OSError
        return False
    return True


def _as_dict(item):
    """ProxyCandidate / dict 统一成可 JSON 化的 dict。"""
    if isinstance(item, dict):
        return {
            "ip": str(item.get("ip", "")),
            "port": int(item.get("port", 0) or 0),
            "latency_ms": int(item.get("latency_ms", 0) or 0),
            "kind": str(item.get("kind", "")),
        }
    return {
        "ip": str(getattr(item, "ip", "")),
        "port": int(getattr(item, "port", 0) or 0),
        "latency_ms": int(getattr(item, "latency_ms", 0) or 0),
        "kind": str(getattr(item, "kind", "")),
    }


def remember_proxy_url(url):
    """记住最近一次使用的代理 URL；空值忽略。"""
    url = (url or "").strip()
    if not url:
        return False
    state = load()
    state["last_proxy_url"] = url
    return save(state)


def get_last_proxy_url(default=""):
    """取记忆的代理 URL。"""
    return load().get("last_proxy_url") or default


def add_scan(subnet, results, *, timestamp):
    """追加一次扫描记录，裁剪到最近 MAX_SCANS 条。"""
    state = load()
    entry = {
        "ts": str(timestamp),
        "subnet": str(subnet or ""),
        "results": [_as_dict(r) for r in (results or [])],
    }
    state["scans"].append(entry)
    state["scans"] = state["scans"][-MAX_SCANS:]
    return save(state)


def scan_history():
    """历史扫描列表，按时间正序。"""
    return list(load()["scans"])


def clear_history():
    """清空扫描历史（保留记忆的 URL）。"""
    state = load()
    state["scans"] = []
    return save(state)


def export_text():
    """把历史导出为可读文本，返回 (文件名, 内容)。"""
    history = scan_history()
    lines = ["代理扫描历史", "=" * 40, f"共 {len(history)} 次扫描", ""]
    for entry in history:
        results = entry.get("results") or []
        lines.append(f"[{entry.get('ts', '')}] 网段 {entry.get('subnet', '')}"
                     f" —— {len(results)} 个可用代理")
        for item in results:
            lines.append(f"    {item.get('ip', '')}:{item.get('port', '')}"
                         f"  {item.get('latency_ms', 0)}ms  {item.get('kind', '')}")
        lines.append("")
    url = get_last_proxy_url()
    if url:
        lines.append(f"最近使用：{url}")
    return "proxy_scan_history.txt", "\n".join(lines)


def export_to_disk():
    """把历史写到 EXPORT_DIR，返回文件绝对路径；失败返回 None。"""
    name, content = export_text()
    try:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        path = os.path.join(EXPORT_DIR, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (OSError, ValueError):
        return None
    return path


def data_dir():
    """数据目录路径（供 UI「打开目录」按钮）。"""
    return os.path.dirname(STORE_PATH) or DATA_DIR
