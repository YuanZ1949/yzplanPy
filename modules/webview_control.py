"""webview_control 模块：msedgewebview2.exe 网络管控，通过 Windows 防火墙规则拦截 + 进程监控。"""
import ctypes
import logging
import os
import subprocess
import threading
import time

from .base import ModuleBase

logger = logging.getLogger("webview_control")

RULE_PREFIX = "YZplan_BlockWebView2"

WEBVIEW2_SEARCH_PATHS = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%LocalAppData%\Microsoft\EdgeWebView2"),
]


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


def scan_processes():
    import psutil
    procs = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "memory_info", "num_threads"]):
        try:
            info = proc.info
            if info["name"] and "msedgewebview2" in info["name"].lower():
                connections = []
                try:
                    for conn in proc.connections(kind="inet"):
                        laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""
                        raddr = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else ""
                        connections.append({
                            "laddr": laddr, "raddr": raddr,
                            "status": conn.status, "type": "TCP",
                        })
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                try:
                    for conn in proc.net_connections():
                        pass
                except Exception:
                    pass
                mem = info.get("memory_info")
                procs.append({
                    "pid": info["pid"],
                    "exe": info.get("exe") or "",
                    "cmdline": " ".join(info.get("cmdline") or []),
                    "rss_mb": round(mem.rss / 1024 / 1024, 1) if mem else 0,
                    "threads": info.get("num_threads", 0),
                    "connections": connections,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


MODULE_INFO = {
    "id": "webview_control",
    "name": "WebView2管控",
    "description": "管理第三方程序对 WebView2 的使用",
}


# ── 第三方程序（WebView2 宿主）检测 / 管控 ─────────────────────────────

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


def load_blocked_exes(config):
    """从 config 读取被拦截的宿主程序 exe 列表。"""
    raw = config.get("webview.blocked_hosts", [])
    if isinstance(raw, str):
        raw = [raw]
    return set(os.path.normcase(x).lower() for x in (raw or []) if x)


def save_blocked_exes(config, blocked):
    config.set("webview.blocked_hosts", sorted(blocked))


class Module(ModuleBase):
    MODULE_ID = "webview_control"
    MODULE_NAME = "WebView2管控"
    MODULE_DESCRIPTION = "管理第三方程序对 WebView2 的使用"
    ENABLED_BY_DEFAULT = False

    def __init__(self, context):
        super().__init__(context)
        self._monitor_running = False
        self._monitor_thread = None
        self._last_hosts = []
        self.blocked = load_blocked_exes(self.context.config)

    def start(self):
        super().start()
        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        self._monitor_running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
            self._monitor_thread = None
        super().stop()

    def _monitor_loop(self):
        while self._monitor_running:
            try:
                # 持续拦截：杀掉仍属于被拦截宿主的 webview 子进程
                if self.blocked:
                    kill_host_webview(self.blocked)
                self._last_hosts = scan_hosts(self.blocked)
            except Exception:
                logger.debug("WebView2 monitor scan failed", exc_info=True)
            for _ in range(30):
                if not self._monitor_running:
                    return
                time.sleep(0.1)

    def set_host_blocked(self, host_exe, blocked):
        """封禁/放行某个第三方程序，并立即终止其 WebView2 进程。"""
        host_exe_n = os.path.normcase(host_exe).lower()
        if blocked:
            self.blocked.add(host_exe_n)
        else:
            self.blocked.discard(host_exe_n)
        save_blocked_exes(self.context.config, self.blocked)
        if blocked:
            kill_host_webview(self.blocked)
        return bool(blocked)

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)


def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 6)
    lay.setSpacing(4)

    title = StrongBodyLabel("WebView2 管控")
    lay.addWidget(title)

    status_lbl = BodyLabel("加载中...")
    status_lbl.setWordWrap(True)
    lay.addWidget(status_lbl)

    btn_row = QtWidgets.QHBoxLayout()
    btn_block = PrimaryPushButton("全部拦截")
    btn_unblock = PushButton("全部放行")
    btn_block.clicked.connect(lambda: _quick_block_all(owner, status_lbl))
    btn_unblock.clicked.connect(lambda: _quick_unblock_all(owner, status_lbl))
    btn_row.addWidget(btn_block)
    btn_row.addWidget(btn_unblock)
    lay.addLayout(btn_row)

    def refresh():
        try:
            hosts = owner._last_hosts if owner._monitor_running else scan_hosts(owner.blocked)
            blocked = sum(1 for h in hosts if blocked_host(h["exe"], owner.blocked))
            lines = [
                f"第三方程序: {len(hosts)} 个",
                f"已封禁: {len(owner.blocked)} 个",
            ]
            status_lbl.setText(" | ".join(lines))
        except Exception as e:
            status_lbl.setText(f"刷新失败: {e}")

    refresh()
    owner._home_refresh = refresh
    return w


def blocked_host(exe, blocked):
    return os.path.normcase(exe).lower() in set(blocked or [])


def _quick_block_all(owner, status_lbl):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()
    try:
        hosts = scan_hosts(owner.blocked)
        exes = [h["exe"] for h in hosts]
        if not exes:
            status_lbl.setText("未检测到使用 WebView2 的第三方程序")
            return
        for exe in exes:
            owner.set_host_blocked(exe, True)
        status_lbl.setText(f"已封禁 {len(exes)} 个程序，并已终止其 WebView2 进程")
        owner._home_refresh()
    except Exception as e:
        status_lbl.setText(f"操作失败: {e}")


def _quick_unblock_all(owner, status_lbl):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()
    try:
        exes = list(owner.blocked)
        if not exes:
            status_lbl.setText("当前没有已封禁的程序")
            return
        for exe in exes:
            owner.set_host_blocked(exe, False)
        status_lbl.setText(f"已放行 {len(exes)} 个程序")
        owner._home_refresh()
    except Exception as e:
        status_lbl.setText(f"操作失败: {e}")


def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    desc = BodyLabel(
        "这里列出使用 WebView2 的第三方程序。封禁后会自动终止该程序的 WebView2 子进程，"
        "并在其后台持续拦截（程序重新打开 WebView2 也会被立即终止）。", w)
    desc.setWordWrap(True)
    desc.setStyleSheet("color: #888;")
    lay.addWidget(desc)

    toolbar = QtWidgets.QHBoxLayout()
    btn_refresh = PushButton("刷新")
    lb_count = BodyLabel("")
    lb_count.setStyleSheet("color: #888;")
    toolbar.addWidget(btn_refresh)
    toolbar.addWidget(lb_count)
    toolbar.addStretch(1)
    lay.addLayout(toolbar)

    table = QtWidgets.QTableWidget()
    table.setColumnCount(4)
    table.setHorizontalHeaderLabels(["程序名", "程序地址", "链接状态", "封禁开关"])
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(table)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    lay.addWidget(table, 1)

    status_bar = BodyLabel("")
    status_bar.setStyleSheet("color: #888;")
    lay.addWidget(status_bar)

    # 已生效/待生效的拦截开关（含重启后仍封禁的宿主导入）
    def _ordered_hosts():
        blocked = set(owner.blocked)
        running = [h for h in scan_hosts(blocked)]
        seen = {h["exe"] for h in running}
        # 补齐已封禁但当前未运行的宿主，方便放行
        for exe in sorted(blocked):
            if exe not in seen:
                running.append({
                    "exe": exe, "name": os.path.basename(exe).replace(".exe", "") or exe,
                    "running": False, "procs": [], "webview_count": 0,
                    "connections": 0, "blocked": True, "user_data_dirs": [],
                })
        running.sort(key=lambda h: (not h["blocked"], h["name"].lower()))
        return running

    def refresh():
        try:
            hosts = _ordered_hosts()
        except Exception as e:
            hosts = []
            status_bar.setText(f"扫描失败: {e}")
        total = len(hosts)
        blocked_count = sum(1 for h in hosts if h["blocked"])
        lb_count.setText(f"{total} 个程序 · 已封禁 {blocked_count}")
        table.setRowCount(len(hosts))
        for i, h in enumerate(hosts):
            # 程序名
            name_item = QtWidgets.QTableWidgetItem(h["name"])
            table.setItem(i, 0, name_item)
            # 程序地址
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(h["exe"]))
            # 链接状态
            if h["blocked"]:
                link_item = QtWidgets.QTableWidgetItem("已拦截")
                link_item.setForeground(QtGui.QColor("#e74c3c"))
            elif not h["running"]:
                link_item = QtWidgets.QTableWidgetItem("未运行")
                link_item.setForeground(QtGui.QColor("#888"))
            elif h["connections"] > 0:
                link_item = QtWidgets.QTableWidgetItem(f"连接中 ({h['connections']} 连接)")
                link_item.setForeground(QtGui.QColor("#27ae60"))
            else:
                link_item = QtWidgets.QTableWidgetItem("运行中·无连接")
                link_item.setForeground(QtGui.QColor("#888"))
            table.setItem(i, 2, link_item)
            # 封禁开关
            sw = QtWidgets.QWidget()
            sl = QtWidgets.QHBoxLayout(sw)
            sl.setContentsMargins(6, 2, 6, 2)
            sl.setSpacing(4)
            sw_btn = QtWidgets.QCheckBox("封禁")
            sw_btn.setChecked(bool(h["blocked"]))
            sw_btn.setStyleSheet("QCheckBox { spacing: 6px; }")
            sw_btn.stateChanged.connect(
                lambda st, exe=h["exe"]: _on_toggle(exe, st != 0, refresh, status_bar)
            )
            sl.addWidget(sw_btn)
            sl.addStretch(1)
            table.setCellWidget(i, 3, sw)
            # 行整行的 checkbox 也可用右键
            table.item(i, 0).setData(QtCore.Qt.UserRole, h["exe"])
        if not hosts:
            status_bar.setText("暂未检测到使用 WebView2 的第三方程序")
        else:
            status_bar.setText("绿色=有网络连接 · 未运行=当前未启动 · 已拦截=封禁生效中（持续杀进程）")

    def _on_toggle(exe, blocked, refresh_fn, status_lbl):
        try:
            owner.set_host_blocked(exe, blocked)
        except Exception as e:
            status_lbl.setText(f"操作失败: {e}")
            refresh_fn()
            return
        if blocked:
            status_lbl.setText(f"已封禁 {os.path.basename(exe)}，其 WebView2 进程已被终止并持续拦截")
        else:
            status_lbl.setText(f"已放行 {os.path.basename(exe)}")
        refresh_fn()

    table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def _menu(pos):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        exe = table.item(row, 0).data(QtCore.Qt.UserRole) if table.item(row, 0) else None
        if not exe:
            return
        menu = QtWidgets.QMenu()
        act = menu.addAction("打开文件位置")
        act2 = menu.addAction("结束该程序的 WebView2 进程")
        if exe in set(owner.blocked):
            act3 = menu.addAction("放行")
        else:
            act3 = menu.addAction("封禁")
        action = menu.exec_(table.mapToGlobal(pos))
        if action == act:
            import subprocess
            try:
                subprocess.Popen(["explorer", "/select,", exe])
            except Exception:
                pass
        elif action == act2:
            n = len(kill_host_webview([exe]))
            status_bar.setText(f"已结束 {n} 个 WebView2 进程")
        elif action == act3:
            blocked = exe in set(owner.blocked)
            _on_toggle(exe, not blocked, refresh, status_bar)

    table.customContextMenuRequested.connect(_menu)

    btn_refresh.clicked.connect(refresh)
    refresh()
    owner._page_refresh = refresh
    return w
