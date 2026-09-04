"""系统托盘：QSystemTrayIcon + 菜单（显示/隐藏、模块快捷入口、退出）。"""

import os
from .qt_bootstrap import import_qt
from .constants import ICON_PATH


class Tray:
    def __init__(self, parent, on_show_home, on_quit, context=None):
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._context = context
        self.menu = QtWidgets.QMenu()
        self.action_show = self.menu.addAction("显示主页")
        self.action_show.triggered.connect(on_show_home)
        self.menu.addSeparator()

        if context is not None:
            self._add_module_actions()

        self.menu.addSeparator()
        self.action_quit = self.menu.addAction("退出")
        self.action_quit.triggered.connect(on_quit)

        if os.path.isfile(ICON_PATH):
            icon = QtGui.QIcon(ICON_PATH)
        else:
            icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.tray = QtWidgets.QSystemTrayIcon(icon, parent)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("YZplan")
        self.tray.activated.connect(self._activated)
        self.tray.show()

    def _add_module_actions(self):
        _, QtCore, QtGui, QtWidgets = import_qt()
        registry = self._context.registry
        for mod in registry.all():
            if not registry.is_enabled(mod.id):
                continue
            if not hasattr(mod, "create_page"):
                continue
            action = self.menu.addAction(mod.name)
            action.triggered.connect(lambda checked=False, m=mod: self._open_module_page(m))

    def _open_module_page(self, mod):
        _, QtCore, QtGui, QtWidgets = import_qt()
        parent = self._context.host_window.window if self._context.host_window else None
        page = mod.create_page(parent)
        if page is None:
            return
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle(mod.name)
        dlg.setMinimumSize(740, 560)
        from core.ui_state import window_geometry
        geometry = window_geometry()
        geometry.apply(dlg, "module_page_" + mod.id, default_size=(740, 560))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, "module_page_" + mod.id))
        dlg.exec()

    def _activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.Trigger:
            self.action_show.trigger()

    def add_module_action(self, text, slot):
        return self.menu.addAction(text, slot)

    def update_tooltip(self, text):
        self.tray.setToolTip(text)

    def set_unread_count(self, count):
        if count > 0:
            self.tray.setToolTip(f"YZplan ({count} 未读)")
            self.tray.showMessage("RSS 更新", f"有 {count} 条未读消息", QtWidgets.QSystemTrayIcon.Information, 2000)
        else:
            self.tray.setToolTip("YZplan")

    def start_mcp_inbox_watcher(self, inbox_dir, interval_ms=2000):
        """轮询 MCP 通知收件箱，弹出托盘通知（供 MCP 接口控制 GUI 使用）。"""
        import json
        from .constants import DATA_DIR
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
            "set_config": lambda: self._mcp_set_config(payload.get("key"), payload.get("value")),
            "toggle_module": lambda: self._mcp_toggle_module(payload.get("module_id"), payload.get("enabled", True)),
            "export_logs": lambda: self._mcp_export_logs(),
            "scan_webview": lambda: self._mcp_scan_webview(),
            "webview_kill": lambda: self._mcp_webview_kill(),
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
        try:
            if not module_id or not self._context:
                return
            if self._context and hasattr(self._context, "host_window") and self._context.host_window:
                host = self._context.host_window.window if hasattr(self._context.host_window, "window") else self._context.host_window
                if hasattr(host, "select_module"):
                    host.select_module(str(module_id))
                host.showNormal()
                host.raise_()
        except Exception:
            pass

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
        from .restart import restart_app
        try:
            restart_app()
        except Exception:
            pass