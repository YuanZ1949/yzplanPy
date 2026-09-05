"""webview_control - firewall (netsh) rule helpers."""
import ctypes
import os
import subprocess
from .constants import RULE_PREFIX, WEBVIEW2_SEARCH_PATHS

def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_netsh(args, elevate=False):
    cmd_list = ["netsh", "advfirewall", "firewall"] + args
    cmd_str = " ".join(cmd_list)
    if elevate and not _is_admin():
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "cmd.exe", f'/c {cmd_str}', None, 1,
            )
            return True, "已请求管理员权限"
        except Exception as e:
            return False, f"提权失败: {e}"
    try:
        result = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return False, str(e)


def find_webview2_paths():
    paths = []
    for base in WEBVIEW2_SEARCH_PATHS:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            full = os.path.join(base, entry, "msedgewebview2.exe")
            if os.path.isfile(full):
                paths.append(full)
        exe = os.path.join(base, "msedgewebview2.exe")
        if os.path.isfile(exe):
            paths.append(exe)
    return sorted(set(paths))


def get_firewall_rules():
    rules = []
    for exe_path in find_webview2_paths():
        for direction, dir_label in [("out", "出站"), ("in", "入站")]:
            rule_name = f"{RULE_PREFIX}_{direction}"
            ok, output = _run_netsh(["show", "rule", f"name={rule_name}", f"program={exe_path}"])
            enabled = "Yes" in output if ok else False
            rules.append({
                "name": rule_name,
                "exe_path": exe_path,
                "direction": direction,
                "dir_label": dir_label,
                "enabled": enabled,
                "exists": ok and "Rule Name" in output,
            })
    return rules


def block_all():
    results = []
    for exe_path in find_webview2_paths():
        for direction in ("out", "in"):
            rule_name = f"{RULE_PREFIX}_{direction}"
            ok, msg = _run_netsh(
                ["add", "rule", f"name={rule_name}", f"dir={direction}",
                 "action=block", f"program={exe_path}", "enable=yes", "profile=any"],
                elevate=True,
            )
            results.append({"exe_path": exe_path, "direction": direction, "ok": ok, "msg": msg})
    return results


def unblock_all():
    results = []
    for exe_path in find_webview2_paths():
        for direction in ("out", "in"):
            rule_name = f"{RULE_PREFIX}_{direction}"
            ok, msg = _run_netsh(
                ["delete", "rule", f"name={rule_name}", f"program={exe_path}"],
                elevate=True,
            )
            results.append({"exe_path": exe_path, "direction": direction, "ok": ok, "msg": msg})
    return results


def toggle_rule(exe_path, direction, enable):
    rule_name = f"{RULE_PREFIX}_{direction}"
    state = "yes" if enable else "no"
    return _run_netsh(
        ["set", "rule", f"name={rule_name}", f"program={exe_path}", "new", f"enable={state}"],
        elevate=True,
    )
