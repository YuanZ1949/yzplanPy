"""系统托盘：QSystemTrayIcon + 分组菜单（显示/隐藏、RSS 快捷、模块、更多/退出）。"""

import os
from .qt_bootstrap import import_qt
from .constants import ICON_PATH

PySide6, QtCore, QtGui, QtWidgets = import_qt()


class Tray:
    def __init__(self, parent, on_show_home, on_quit, context=None):
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._context = context
        self._on_show_home = on_show_home
        self._on_quit = on_quit
        self.menu = QtWidgets.QMenu()
        self._dialogs = set()   # 保持非模态对话框引用，防止被回收消失

        # 每次菜单弹出前整体重建：保证未读数/模块列表/窗口状态实时同步
        self.menu.aboutToShow.connect(self._rebuild)

        # 构建一级分组菜单（初始不弹通知）
        self._rebuild(notify=False)

        if os.path.isfile(ICON_PATH):
            icon = QtGui.QIcon(ICON_PATH)
        else:
            icon = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.tray = QtWidgets.QSystemTrayIcon(icon, parent)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("YZplan")
        self.tray.activated.connect(self._activated)
        self.tray.show()

    # ── 菜单构建 ──────────────────────────────────────────────────────

    def _host_window(self):
        """返回实际 Qt 窗口对象（MainWindow 包装上的 .window）。"""
        if not self._context:
            return None
        win = self._context.host_window
        if win is None:
            return None
        _, _, _, QtWidgets = import_qt()
        # MainWindow 包装对象：.window 是真实 Qt 窗口（QWidget 的 window() 是方法，需排除）
        attr = getattr(win, "window", None)
        if attr is not None and not callable(attr) and isinstance(attr, QtWidgets.QWidget):
            return attr
        return win

    def _rebuild(self, notify=True):
        """重建一级分组菜单：显示/隐藏 → RSS 快捷 → 模块 → 更多 → 退出。"""
        self.menu.clear()

        # 显示主页 / 隐藏到托盘（互斥勾选项）
        self.action_show = self.menu.addAction("显示主页")
        self.action_show.setCheckable(True)
        win = self._host_window()
        if win is not None:
            self.action_show.setChecked(win.isVisible())
        self.action_show.triggered.connect(self._toggle_home)

        self.menu.addSeparator()

        # RSS 快捷访问（未读数保留在一级）
        rss = self._rss_module()
        if rss is not None:
            act_open = self.menu.addAction("打开 RSS 聚合")
            act_open.triggered.connect(lambda: self._open_module_page(rss))
            act_refresh = self.menu.addAction("立即刷新所有源")
            act_refresh.triggered.connect(self._refresh_rss_now)

            try:
                count = rss.store.get_unread_count()
            except Exception:
                count = 0
            lb = self.menu.addAction(f"当前未读：{count}")
            lb.setEnabled(False)
            if notify:
                self.set_unread_count(count)

            self.menu.addSeparator()

        # 模块快捷入口（一级）
        if not self._add_module_actions():
            item = self.menu.addAction("（暂无可用模块）")
            item.setEnabled(False)
            self.menu.addSeparator()

        # 更多（设置 / 关于 / 重启）
        act_settings = self.menu.addAction("程序设置")
        act_settings.triggered.connect(self._open_settings_dialog)
        act_about = self.menu.addAction("关于")
        act_about.triggered.connect(self._open_about_dialog)
        act_restart = self.menu.addAction("重启程序")
        act_restart.triggered.connect(self._confirm_restart)

        self.menu.addSeparator()
        self.action_quit = self.menu.addAction("退出")
        self.action_quit.triggered.connect(self._on_quit)

    def _rss_module(self):
        if not self._context or not hasattr(self._context, "registry"):
            return None
        mod = self._context.registry.get("rss_aggregator")
        if mod is None or not self._context.registry.is_enabled(mod.id):
            return None
        return mod

    def _add_module_actions(self):
        """添加启用且含 create_page 的模块为一级菜单项；返回是否添加了任何项。"""
        if not self._context or not hasattr(self._context, "registry"):
            return False
        registry = self._context.registry
        added = False
        for mod in registry.all():
            if not registry.is_enabled(mod.id):
                continue
            if not hasattr(mod, "create_page"):
                continue
            act = self.menu.addAction(mod.name)
            act.triggered.connect(lambda checked=False, m=mod: self._open_module_page(m))
            added = True
        return added

    def _refresh_rss_now(self):
        rss = self._rss_module()
        if rss is None:
            return
        try:
            rss.refresh_now()
        except Exception:
            pass

    def _open_module_page(self, mod):
        from ui.module_pages import open_module_page
        try:
            open_module_page(mod)
        except Exception:
            pass

    def _toggle_home(self, checked):
        """“显示主页”勾选项：勾选→显示，取消→隐藏。"""
        win = self._host_window()
        if win is None:
            if checked:
                self._on_show_home()
            return
        if checked is not None:
            if checked:
                self.show_home()
            else:
                win.hide()

    def show_home(self):
        if self._on_show_home is not None:
            self._on_show_home()

    def _on_quit(self):
        if self._on_quit is not None:
            self._on_quit()

    # ── 更多：设置 / 关于 / 重启 ─────────────────────────────────────

    def _open_settings_dialog(self):
        """程序设置对话框（与主窗口标题栏设置按钮一致）。"""
        from ui.settings_tab import SettingsTab
        from core.ui_state import window_geometry
        _, QtCore, QtGui, QtWidgets = import_qt()
        dlg = QtWidgets.QDialog()
        dlg.setWindowTitle("程序设置")
        dlg.setMinimumSize(600, 500)
        geometry = window_geometry()
        geometry.apply(dlg, "settings_dialog", default_size=(600, 500))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        tab = SettingsTab(self._context)
        lay.addWidget(tab.widget)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, "settings_dialog"))
        self._keep_dialog(dlg)
        dlg.show()

    def _open_about_dialog(self):
        """轻量“关于”对话框（复用 AboutTab 内容页）。"""
        from ui.about_tab import AboutTab
        from core.ui_state import window_geometry
        _, QtCore, QtGui, QtWidgets = import_qt()
        dlg = QtWidgets.QDialog()
        dlg.setWindowTitle("关于 YZplan")
        dlg.setMinimumSize(480, 400)
        geometry = window_geometry()
        geometry.apply(dlg, "about_dialog", default_size=(480, 400))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        tab = AboutTab(self._context)
        lay.addWidget(tab.widget)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, "about_dialog"))
        self._keep_dialog(dlg)
        dlg.show()

    def _keep_dialog(self, dlg):
        """保持对话框引用存活，关闭后自动释放。"""
        self._dialogs.add(dlg)
        dlg.destroyed.connect(lambda *_: self._dialogs.discard(dlg))

    def _confirm_restart(self):
        """重启程序：确认后释放单实例锁并重启（与标题栏重启按钮一致）。"""
        _, QtCore, QtGui, QtWidgets = import_qt()
        reply = QtWidgets.QMessageBox.question(
            None, "重启确认",
            "确定要重启程序吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        si = getattr(self._context, "si", None)
        if si:
            try:
                si.release()
            except Exception:
                pass
        from core.restart import restart_app
        try:
            restart_app()
        except Exception:
            pass

    def _activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.Trigger:
            # 单击托盘图标：刷新显示状态后显示主页
            win = self._host_window()
            if win is not None:
                self.action_show.setChecked(win.isVisible())
            self.show_home()

    def add_module_action(self, text, slot):
        return self.menu.addAction(text, slot)

    def update_tooltip(self, text):
        self.tray.setToolTip(text)

    def set_unread_count(self, count):
        """更新托盘 tooltip（未读数变化时弹一次通知）。"""
        count = max(0, int(count or 0))
        if count > 0:
            self.tray.setToolTip(f"YZplan ({count} 未读)")
            if getattr(self, "_last_unread", 0) != count:
                self.tray.showMessage("RSS 更新", f"有 {count} 条未读消息",
                                      QtWidgets.QSystemTrayIcon.Information, 2000)
        else:
            self.tray.setToolTip("YZplan")
        self._last_unread = count

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