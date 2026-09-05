"""系统托盘：MCP 收件箱轮询、命令分发与重启调度。"""

import os
from ..qt_bootstrap import import_qt
from .dialogs import Tray

class Tray(Tray):


    def start_mcp_inbox_watcher(self, inbox_dir, interval_ms=2000):
        """轮询 MCP 通知收件箱，弹出托盘通知（供 MCP 接口控制 GUI 使用）。"""
        import json
        from ..constants import DATA_DIR
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._mcp_inbox_dir = inbox_dir
        self._mcp_timer = QtCore.QTimer()
        self._mcp_timer.setInterval(interval_ms)

        def _poll():
            try:
                if not os.path.isdir(inbox_dir):
                    return
                for name in sorted(os.listdir(inbox_dir)):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(inbox_dir, name)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                        os.remove(path)
                        self._dispatch_mcp_command(payload)
                        if not payload.get("silent"):
                            title = payload.get("title", "YZplan")
                            message = payload.get("message", "")
                            level = payload.get("level", "info")
                            icon = QtWidgets.QSystemTrayIcon.Information
                            if level == "warning":
                                icon = QtWidgets.QSystemTrayIcon.Warning
                            elif level == "error":
                                icon = QtWidgets.QSystemTrayIcon.Critical
                            elif level == "success":
                                icon = QtWidgets.QSystemTrayIcon.Information
                            self.tray.showMessage(title, message, icon, 3000)
                    except Exception:
                        pass
            except Exception:
                pass

        self._mcp_timer.timeout.connect(_poll)
        self._mcp_timer.start()
        return self._mcp_timer

    def _dispatch_mcp_command(self, payload):
        """分发 MCP inbox 命令到对应处理方法。"""
        command = payload.get("command")
        if not command:
            return
        dispatch = {
            "restart": lambda: self._schedule_restart(payload.get("delay_seconds", 0)),
            "refresh_feeds": lambda: self._mcp_refresh_feeds(),
            "refresh_aggregation": lambda: self._mcp_refresh_aggregation(payload.get("agg_id")),
            "show_window": lambda: self._mcp_show_window(),
            "navigate_module": lambda: self._mcp_navigate_module(payload.get("module_id")),
            "open_module_page": lambda: self._mcp_open_module_page(payload.get("module_id")),
            "set_config": lambda: self._mcp_set_config(payload.get("key"), payload.get("value")),
            "toggle_module": lambda: self._mcp_toggle_module(payload.get("module_id"), payload.get("enabled", True)),
            "export_logs": lambda: self._mcp_export_logs(),
            "scan_webview": lambda: self._mcp_scan_webview(),
            "webview_kill": lambda: self._mcp_webview_kill(),
            "rss_preview": lambda: self._mcp_rss_preview(payload.get("hash"), payload.get("link")),
            "perf_stats_request": lambda: self._mcp_perf_stats_reply(payload.get("reply_file")),
            "quit": lambda: self._mcp_quit(),
        }
        handler = dispatch.get(command)
        if handler:
            try:
                handler()
            except Exception:
                pass

    def _mcp_refresh_feeds(self):
        try:
            if self._context and hasattr(self._context, "registry"):
                for mod in self._context.registry.all():
                    if mod.id == "rss_aggregator" and hasattr(mod, "refresh_now"):
                        mod.refresh_now()
                        break
        except Exception:
            pass

    def _mcp_refresh_aggregation(self, agg_id):
        try:
            if agg_id is None:
                return
            if self._context and hasattr(self._context, "registry"):
                for mod in self._context.registry.all():
                    if mod.id == "rss_aggregator" and hasattr(mod, "refresh_aggregation"):
                        mod.refresh_aggregation(int(agg_id))
                        break
        except Exception:
            pass

    def _mcp_rss_preview(self, hash_, link):
        """触发 RSS 条目预览（通过 MCP inbox）。"""
        try:
            if not hash_ or not self._context:
                return
            if self._context and hasattr(self._context, "registry"):
                for mod in self._context.registry.all():
                    if mod.id == "rss_aggregator" and hasattr(mod, "trigger_preview"):
                        mod.trigger_preview(str(hash_), str(link or ""))
                        break
        except Exception:
            pass

    def _mcp_open_module_page(self, module_id):
        """打开指定模块页面（通过 MCP inbox）。"""
        try:
            if not module_id or not self._context or not hasattr(self._context, "registry"):
                return
            mod = self._context.registry.get(str(module_id))
            if mod is None or not hasattr(mod, "create_page"):
                return
            from ui.module_pages import open_module_page
            open_module_page(mod)
        except Exception:
            pass

    def _mcp_perf_stats_reply(self, reply_file):
        """响应 MCP 的 perf_stats 请求：把本进程 core.perf 统计写回 reply_file。

        数据源与性能监测面板图表一致（同一进程内内存 `_records`）。
        """
        try:
            if not reply_file:
                return
            from core import perf
            data = {
                "enabled": perf.is_enabled(),
                "uptime_s": round(perf.uptime_seconds(), 1),
                "rows": perf.stats(),
            }
            import json
            with open(reply_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _mcp_show_window(self):
        try:
            if self._context and self._context.host_window:
                win = self._context.host_window.window if hasattr(self._context.host_window, "window") else self._context.host_window
                win.showNormal()
                win.raise_()
                win.activateWindow()
        except Exception:
            pass

    def _mcp_navigate_module(self, module_id):
        """导航到指定模块页面（通过 MCP inbox）。

        历史死路径：旧实现调用 host.select_module()，而 MainWindow 上并不存在
        该方法（select_module 未实现），hasattr 判定恒为 False，命令静默无效。
        本应用中模块页面统一通过 ui.module_pages.open_module_page 打开
        （每模块全局单例窗口，modules_tab / 托盘菜单共用），
        因此导航复用 open_module_page 路径。
        """
        self._mcp_open_module_page(module_id)

    def _mcp_set_config(self, key, value):
        try:
            if not key or not self._context:
                return
            if hasattr(self._context, "config"):
                self._context.config.set(key, value)
                if key.startswith("modules.") and key.endswith(".enabled"):
                    mod_id = key.split(".")[1]
                    enabled = bool(value)
                    if hasattr(self._context, "registry"):
                        self._context.registry.set_enabled(mod_id, enabled)
        except Exception:
            pass

    def _mcp_toggle_module(self, module_id, enabled):
        try:
            if not module_id or not self._context:
                return
            if hasattr(self._context, "config"):
                self._context.config.set_module_enabled(str(module_id), bool(enabled))
        except Exception:
            pass

    def _mcp_export_logs(self):
        try:
            from core.logger import get_memory_logs
            from core.constants import DATA_DIR
            logs = list(get_memory_logs(limit=5000))
            export_path = os.path.join(DATA_DIR, "logs_export.txt")
            with open(export_path, "w", encoding="utf-8") as f:
                for entry in logs:
                    f.write(f"{entry.get('time', '')} | {entry.get('level', '')} | {entry.get('source', '')} | {entry.get('message', '')}\n")
        except Exception:
            pass

    def _mcp_scan_webview(self):
        try:
            if self._context and hasattr(self._context, "registry"):
                for mod in self._context.registry.all():
                    if hasattr(mod, "refresh_list"):
                        mod.refresh_list()
                        break
        except Exception:
            pass

    def _mcp_webview_kill(self):
        try:
            import subprocess
            subprocess.run("taskkill /F /IM msedgewebview2.exe", shell=True,
                           capture_output=True, timeout=5, creationflags=0x08000000)
        except Exception:
            pass

    def _mcp_quit(self):
        try:
            _, _, _, QtWidgets = import_qt()
            QtWidgets.QApplication.quit()
        except Exception:
            pass

    def _schedule_restart(self, delay_seconds=0):
        """延迟后在主线程执行程序完全重启（供 MCP app_restart 使用）。"""
        _, QtCore, _, _ = import_qt()
        try:
            delay_ms = max(0, int(delay_seconds or 0)) * 1000
            QtCore.QTimer.singleShot(delay_ms, self._do_restart)
        except Exception:
            pass

    def _do_restart(self):
        from ..restart import restart_app
        try:
            restart_app()
        except Exception:
            pass
