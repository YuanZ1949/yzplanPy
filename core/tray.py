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