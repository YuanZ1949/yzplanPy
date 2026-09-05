"""系统托盘：设置 / 关于 / 未读提醒等次要对话框方法。"""

from ..qt_bootstrap import import_qt

PySide6, QtCore, QtGui, QtWidgets = import_qt()
from .tray_base import Tray

class Tray(Tray):


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
