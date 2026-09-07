"""webview_control - Module class."""
import logging
import os
import threading
import time
logger = logging.getLogger("webview_control")
from ..base import ModuleBase
from .config import load_blocked_exes, save_blocked_exes, load_host_log, save_host_log
from .hosts import kill_host_webview, scan_hosts
from .home import _make_home_widget
from .page import _make_page_widget

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
        self.host_log = load_host_log(self.context.config)

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
        # 在监控线程中永久禁用自动 GC，防止 psutil.process_iter() 触发 GC 回收 Qt 对象
        import gc
        gc.disable()
        while self._monitor_running:
            try:
                # 持续拦截：杀掉仍属于被拦截宿主的 webview 子进程
                if self.blocked:
                    kill_host_webview(self.blocked)
                self._last_hosts = scan_hosts(self.blocked)
                self._record_hosts(self._last_hosts)
            except Exception:
                logger.debug("WebView2 monitor scan failed", exc_info=True)
            for _ in range(30):
                if not self._monitor_running:
                    return
                time.sleep(0.1)

    def _record_hosts(self, hosts):
        """记录扫描到的宿主：未拦截宿主存在→更新 last_seen，新增→pending；
        被拦截宿主标记 blocked。不自动拦截任何新宿主。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        by_exe = {e["exe"]: e for e in self.host_log}
        for h in hosts:
            exe = h["exe"]
            if exe in by_exe:
                ent = by_exe[exe]
                ent["last_seen"] = now
                if h["blocked"]:
                    ent["status"] = "blocked"
            else:
                self.host_log.append({
                    "exe": exe,
                    "name": h["name"],
                    "first_seen": now,
                    "last_seen": now,
                    "status": "blocked" if h["blocked"] else "pending",
                })
        save_host_log(self.context.config, self.host_log)

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

    def set_host_handler(self, host_exe, action):
        """处置宿主记录：allow=放行、block=拦截、forget=删除记录（并同步封禁集合）。"""
        host_exe_n = os.path.normcase(host_exe).lower()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if action == "allow":
            self.set_host_blocked(host_exe_n, False)
            for ent in self.host_log:
                if ent["exe"] == host_exe_n:
                    ent["status"] = "allowed"
                    ent["last_seen"] = now
                    break
            else:
                self.host_log.append({
                    "exe": host_exe_n,
                    "name": os.path.basename(host_exe_n).replace(".exe", "") or host_exe_n,
                    "first_seen": now,
                    "last_seen": now,
                    "status": "allowed",
                })
        elif action == "block":
            self.set_host_blocked(host_exe_n, True)
            for ent in self.host_log:
                if ent["exe"] == host_exe_n:
                    ent["status"] = "blocked"
                    ent["last_seen"] = now
                    break
            else:
                self.host_log.append({
                    "exe": host_exe_n,
                    "name": os.path.basename(host_exe_n).replace(".exe", "") or host_exe_n,
                    "first_seen": now,
                    "last_seen": now,
                    "status": "blocked",
                })
        elif action == "forget":
            self.blocked.discard(host_exe_n)
            save_blocked_exes(self.context.config, self.blocked)
            self.host_log = [e for e in self.host_log if e["exe"] != host_exe_n]
        else:
            raise ValueError(f"未知处置动作: {action}")
        save_host_log(self.context.config, self.host_log)
        return True

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)
