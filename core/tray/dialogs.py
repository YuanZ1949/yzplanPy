"""系统托盘：设置 / 关于 / 未读提醒等次要对话框方法。"""

from ..qt_bootstrap import import_qt

PySide6, QtCore, QtGui, QtWidgets = import_qt()
from .tray_base import Tray

class Tray(Tray):  # type: ignore[reportGeneralTypeIssues]


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

    # ── 勾选框边框（任务13）───────────────────────────────────────

    _MENU_CHECKBOX_QSS_MARK = "/* yzplan-tray-checkbox */"

    def _apply_menu_checkbox_style(self):
        """为托盘菜单勾选项（QMenu::indicator）补充清晰边框。

        全局主题只样式化了 QCheckBox::indicator，未覆盖 QMenu::indicator，
        导致托盘菜单中“显示主页”勾选框回退到平台默认渲染、边框不可见。
        在菜单自身样式表上追加 indicator 规则（保留主题其余规则），
        边框颜色按当前深/浅主题取对比色，主题切换后重建时自动刷新。
        """
        from ..theme import resolve_dark
        dark = resolve_dark("auto")
        border = "rgba(255,255,255,0.50)" if dark else "rgba(0,0,0,0.50)"
        block = (
            self._MENU_CHECKBOX_QSS_MARK + "\n"
            "QMenu::indicator {\n"
            "    width: 16px;\n"
            "    height: 16px;\n"
            f"    border: 1px solid {border};\n"
            "    border-radius: 3px;\n"
            "    background: transparent;\n"
            "}\n"
            "QMenu::indicator:checked {\n"
            "    background: rgba(0,120,215,0.85);\n"
            "    border: 1px solid rgba(0,120,215,0.9);\n"
            "}\n"
        )
        base = self.menu.styleSheet()
        idx = base.find(self._MENU_CHECKBOX_QSS_MARK)
        if idx >= 0:
            base = base[:idx].rstrip()
        self.menu.setStyleSheet((base + "\n" + block) if base else block)

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
        if reason == QSystemTrayIcon.Trigger:  # type: ignore[reportAttributeAccessIssue]
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
        """更新托盘 tooltip（未读数仅在 tooltip 显示，不弹 Windows 通知）。"""
        count = max(0, int(count or 0))
        if count > 0:
            self.tray.setToolTip(f"YZplan ({count} 未读)")
        else:
            self.tray.setToolTip("YZplan")
        self._last_unread = count
