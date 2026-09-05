"""webview_control - WebView2 host detection and control."""
import os

def _is_webview_pid(pid):
    import psutil
    try:
        return "msedgewebview2" in (psutil.Process(pid).name() or "").lower()
    except Exception:
        return False


def _proc_exe_path(pid):
    import psutil
    try:
        return os.path.normcase(psutil.Process(pid).exe() or "").lower()
    except Exception:
        return ""


def _host_signature_for_webview(wpid):
    """对某 msedgewebview2 进程向上追溯父母链，找到发起它的第三方宿主程序。

    返回 (host_exe_norm, user_data_dir) ；找不到宿主则返回 (None, None)。
    """
    import psutil
    try:
        proc = psutil.Process(wpid)
    except Exception:
        return None, None
    user_data_dir = ""
    try:
        for a in (proc.cmdline() or []):
            if a.startswith("--user-data-dir="):
                user_data_dir = os.path.normcase(a.split("=", 1)[1]).lower()
                break
    except Exception:
        pass
    # 向上追溯，找到第一个非 msedgewebview2 的祖先进程作为宿主
    try:
        parent = proc.parent()
        seen = 0
        while parent is not None and seen < 12:
            try:
                pname = (parent.name() or "").lower()
                if "msedgewebview2" not in pname and "msedge" not in pname:
                    exe = parent.exe()
                    return os.path.normcase(exe).lower(), user_data_dir
                parent = parent.parent()
                seen += 1
            except Exception:
                break
    except Exception:
        pass
    return None, user_data_dir


def scan_hosts(blocked_exes):
    """扫描当前正在使用 WebView2 的第三方宿主程序。

    返回按宿主 exe 聚合的条目列表：
    {exe, name, running, procs, webview_count, connections, blocked, user_data_dirs}
    """
    import psutil
    blocked = set(blocked_exes or [])
    hosts = {}
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            if not (info["name"] or "").lower().count("msedgewebview2"):
                continue
            host_exe, udd = _host_signature_for_webview(info["pid"])
            if not host_exe:
                continue
            ent = hosts.setdefault(host_exe, {
                "exe": host_exe,
                "name": os.path.basename(host_exe).replace(".exe", "") or host_exe,
                "running": False,
                "procs": [],
                "webview_count": 0,
                "connections": 0,
                "blocked": host_exe in blocked,
                "user_data_dirs": set(),
            })
            ent["webview_count"] += 1
            if udd:
                ent["user_data_dirs"].add(udd)
            # 宿主进程本身
            if not ent["procs"]:
                hp = _host_pid(host_exe)
                if hp:
                    ent["procs"].append(hp)
            ent["running"] = True
            # 统计该宿主 webview 的连接数
            try:
                ent["connections"] += len(proc.net_connections(kind="inet"))
            except Exception:
                pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    result = []
    for exe, ent in hosts.items():
        ent["user_data_dirs"] = sorted(ent["user_data_dirs"])
        result.append(ent)
    result.sort(key=lambda e: (not e["blocked"], e["name"].lower()))
    return result


def _host_pid(host_exe):
    """按 exe 路径找宿主进程的 pid（用于展示）。"""
    import psutil
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            if os.path.normcase((p.info["exe"] or "")).lower() == host_exe:
                return p.info["pid"]
        except Exception:
            continue
    return None


def kill_host_webview(blocked_exes):
    """终止被拦截宿主所发起的 msedgewebview2 子进程（以及残留的孤儿进程）。

    返回被杀死的进程 pid 列表。
    """
    import psutil
    blocked = set(blocked_exes or [])
    killed = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if "msedgewebview2" not in (proc.info["name"] or "").lower():
                continue
            host_exe, _ = _host_signature_for_webview(proc.info["pid"])
            if host_exe in blocked:
                proc.kill()
                killed.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed
