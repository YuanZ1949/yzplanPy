"""系统托盘：QSystemTrayIcon + 分组菜单（显示/隐藏、RSS 快捷、模块、更多/退出）— 基础与菜单构建。"""

import os
from ..qt_bootstrap import import_qt
from ..constants import ICON_PATH

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
        self.tray.activated.connect(self._activated)  # type: ignore[reportAttributeAccessIssue]
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
                self.set_unread_count(count)  # type: ignore[reportAttributeAccessIssue]

            self.menu.addSeparator()

        # 模块快捷入口（一级）
        if not self._add_module_actions():
            item = self.menu.addAction("（暂无可用模块）")
            item.setEnabled(False)
            self.menu.addSeparator()

        # 更多（设置 / 关于 / 重启）
        act_settings = self.menu.addAction("程序设置")
        act_settings.triggered.connect(self._open_settings_dialog)  # type: ignore[reportAttributeAccessIssue]
        act_about = self.menu.addAction("关于")
        act_about.triggered.connect(self._open_about_dialog)  # type: ignore[reportAttributeAccessIssue]
        act_restart = self.menu.addAction("重启程序")
        act_restart.triggered.connect(self._confirm_restart)  # type: ignore[reportAttributeAccessIssue]

        self.menu.addSeparator()
        self.action_quit = self.menu.addAction("退出")
        self.action_quit.triggered.connect(self._on_quit)

        # 样式约束：菜单项（按钮）尺寸一致 + 勾选框清晰边框（dialogs.py 提供）
        self._apply_menu_item_sizing()
        apply_checkbox = getattr(self, "_apply_menu_checkbox_style", None)
        if apply_checkbox is not None:
            apply_checkbox()

    # ── 菜单项尺寸约束（任务14）───────────────────────────────────

    _MENU_ITEM_QSS_MARK = "/* yzplan-tray-item-size */"

    def _apply_menu_item_sizing(self):
        """约束菜单项（按钮）尺寸：字体/图标变化时保持一致的项高与菜单宽度。

        托盘菜单项即“按钮”。QMenu::item 设置 min-height 兜底项高，
        菜单设置最小宽度，避免字体/图标变化导致菜单忽大忽小。
        行列高 = max(min-height, 文字高 + 上下 padding)：全局主题 QMenu::item
        带 6px 上下 padding，叠加后每行约 29px 偏大；这里用菜单自身样式表
        （优先级高于全局）把 padding 压到 3px、min-height 降到 20px，
        使每行约 23px（文字 17px + 6px），整体更紧凑。
        """
        block = (
            self._MENU_ITEM_QSS_MARK + "\n"
            "QMenu::item {\n"
            "    min-height: 20px;\n"
            "    padding: 3px 24px 3px 12px;\n"
            "}\n"
        )
        base = self.menu.styleSheet()
        idx = base.find(self._MENU_ITEM_QSS_MARK)
        if idx >= 0:
            base = base[:idx].rstrip()
        self.menu.setStyleSheet((base + "\n" + block) if base else block)
        self.menu.setMinimumWidth(180)

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
