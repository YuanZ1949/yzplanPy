"""主窗口：Fluent 风格导航界面（主页/模块/设置/关于），支持壁纸背景与毛玻璃，关闭时最小化到托盘。
标题栏自定义按钮（带文字、按功能分组，组间以分隔线隔离）：
主页操作组——添加组件、布局（重置/清空）；程序操作组——设置、日志（带异常红点）、重启。"""
import os
from core.qt_bootstrap import import_qt
from qfluentwidgets import (
    FluentIcon,
    FluentTitleBar,
    FluentTitleBarButton,
    FluentWindow,
    NavigationItemPosition,
)
from core.theme import paint_wallpaper_glass as _paint_wallpaper_glass

_, QtCore, QtGui, QtWidgets = import_qt()


class _BadgeWidget(QtWidgets.QWidget):
    """叠加在按钮右上角的红色通知徽章。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self.setFixedSize(18, 18)
        self.hide()

    def set_count(self, count):
        self._count = count
        self.setVisible(count > 0)
        self.update()

    def paintEvent(self, event):
        if self._count <= 0:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QColor(220, 38, 38))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(1, 1, 16, 16)
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.setFont(QtGui.QFont("Microsoft YaHei", 7, QtGui.QFont.Bold))
        text = str(min(self._count, 99))
        painter.drawText(self.rect(), QtCore.Qt.AlignCenter, text)
        painter.end()


class _TextTitleBarButton(FluentTitleBarButton):
    """带文字的标题栏按钮：图标+文字。

    复用 TitleBarButton 状态机（NORMAL/HOVER/PRESSED）与 _getColors()，
    文字与图标使用同一主题色（由 FLUENT_WINDOW QSS 注入），
    因此与纯图标标题栏按钮的外观风格完全统一。
    """

    _FONT = QtGui.QFont("Microsoft YaHei", 9)

    def __init__(self, icon, text, parent=None):
        super().__init__(icon, parent)
        self._text = text
        metric = QtGui.QFontMetrics(self._FONT)
        tw = metric.horizontalAdvance(text)
        # 紧凑规格：固定高 28、最小宽 0、水平 Maximum（可收缩不可扩张）、内边距 2px 8px
        self.setFixedHeight(28)
        self.setMinimumWidth(0)
        self.setMaximumWidth(14 + 6 + tw + 16)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        metric = QtGui.QFontMetrics(self._FONT)
        tw = metric.horizontalAdvance(self._text)
        # 图标 14 + 间距 6 + 文字 + 两侧内边距 16（8px/侧）
        return QtCore.QSize(14 + 6 + tw + 16, 28)

    def paintEvent(self, event):
        from qfluentwidgets.common.icon import drawIcon

        painter = QtGui.QPainter(self)
        painter.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform
        )
        color, bg_color = self._getColors()

        # 背景（与原生标题栏按钮一致）
        painter.setBrush(bg_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(self.rect())

        # 图标（左侧）
        drawIcon(self._icon, painter, QtCore.QRectF(8, (self.height() - 14) / 2, 14, 14))

        # 文字（与图标同色，主题自适应）
        painter.setPen(color)
        painter.setFont(self._FONT)
        painter.drawText(
            QtCore.QRectF(8 + 14 + 6, 0, self.width() - (8 + 14 + 6) - 8, self.height()),
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
            self._text,
        )


class _VLine(QtWidgets.QWidget):
    """标题栏竖向分隔线（主题自适应细线），用于功能分组隔离。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 与按钮同高，保证进出 buttonLayout 后垂直对齐一致；线画在垂直居中。
        self.setFixedSize(10, 28)

    def paintEvent(self, event):
        from core.theme import resolve_dark

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if resolve_dark("auto"):
            color = QtGui.QColor(255, 255, 255, 50)
        else:
            color = QtGui.QColor(0, 0, 0, 30)
        painter.setPen(color)
        painter.drawLine(5, 6, 5, self.height() - 6)
        painter.end()


class _CustomTitleBar(FluentTitleBar):
    """自定义标题栏：主页操作（添加组件/布局）与程序操作（设置/日志/重启）
    分组排布在窗口控制按钮前，组间以分隔线隔离。"""

    def __init__(self, parent, owner):
        super().__init__(parent)
        self._owner = owner

        # ── 主页操作组 ──────────────────────────────────────────────
        self.addBtn = _TextTitleBarButton(FluentIcon.ADD, "添加组件", self)
        self.addBtn.setToolTip("向主页添加组件")
        self.addBtn.clicked.connect(self._open_add_popup)

        self.layoutBtn = _TextTitleBarButton(FluentIcon.LAYOUT, "布局", self)
        self.layoutBtn.setToolTip("主页布局")
        self._layout_menu = QtWidgets.QMenu(self.window())
        self._layout_menu.addAction("重置布局", self._reset_layout)
        self._layout_menu.addAction("清空布局", self._clear_layout)
        self.layoutBtn.clicked.connect(self._open_layout_menu)

        self._sep = _VLine(self)

        # ── 程序操作组 ──────────────────────────────────────────────
        self.settingsBtn = _TextTitleBarButton(FluentIcon.SETTING, "设置", self)
        self.settingsBtn.setToolTip("程序设置")
        self.settingsBtn.clicked.connect(self._open_settings)

        self.logBtn = _TextTitleBarButton(FluentIcon.HISTORY, "日志", self)
        self.logBtn.setToolTip("运行日志")
        self.logBtn.clicked.connect(self._open_log)

        self.restartBtn = _TextTitleBarButton(FluentIcon.UPDATE, "重启", self)
        self.restartBtn.setToolTip("重启程序")
        self.restartBtn.clicked.connect(self._restart)

        self._badge = _BadgeWidget(self.logBtn)

        self.buttonLayout.insertWidget(0, self.addBtn)
        self.buttonLayout.insertWidget(1, self.layoutBtn)
        self.buttonLayout.insertWidget(2, self._sep)
        self.buttonLayout.insertWidget(3, self.settingsBtn)
        self.buttonLayout.insertWidget(4, self.logBtn)
        self.buttonLayout.insertWidget(5, self.restartBtn)

        from core.logger import on_error_count_changed
        on_error_count_changed(self._on_error_count)

    def _open_add_popup(self):
        home = getattr(self._owner, "home_tab", None)
        if home is not None:
            home._show_add_popup(anchor=self.addBtn)

    def _open_layout_menu(self):
        self._layout_menu.popup(
            self.layoutBtn.mapToGlobal(QtCore.QPoint(0, self.layoutBtn.height()))
        )

    def _home(self):
        return getattr(self._owner, "home_tab", None)

    def _reset_layout(self):
        home = self._home()
        if home is not None:
            home._reset_layout()

    def _clear_layout(self):
        home = self._home()
        if home is not None:
            home._clear_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_badge()

    def _position_badge(self):
        self._badge.move(self.logBtn.width() - 15, -2)

    def _on_error_count(self, count):
        self._badge.set_count(count)
        self._position_badge()

    def _open_settings(self):
        from ui.settings_tab import SettingsTab
        dlg = QtWidgets.QDialog(self.window())
        dlg.setWindowTitle("程序设置")
        dlg.setMinimumSize(600, 500)
        from core.ui_state import window_geometry
        geometry = window_geometry()
        geometry.apply(dlg, "settings_dialog", default_size=(600, 500))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        tab = SettingsTab(self._owner.context)
        lay.addWidget(tab.widget)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, "settings_dialog"))
        dlg.exec()

    def _open_log(self):
        from core.logger import reset_error_count
        reset_error_count()
        self._badge.set_count(0)
        from ui.log_viewer import LogViewerDialog
        dlg = LogViewerDialog(self.window())
        dlg.exec()

    def _restart(self):
        reply = QtWidgets.QMessageBox.question(
            self.window(), "重启确认",
            "确定要重启程序吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        si = getattr(self._owner.context, "si", None)
        if si:
            si.release()
        from core.restart import restart_app
        restart_app()


class MainWindow:
    def __init__(self, context):
        class _Window(FluentWindow):
            def __init__(self, owner):
                super().__init__()
                self._owner = owner
                self._first_show = True
                self._apply_geometry()

            def _apply_geometry(self):
                from core.ui_state import window_geometry

                if window_geometry().apply(self, "main_window", min_fit_ratio=0.55):
                    return
                screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
                if screen is None:
                    screen = QtGui.QGuiApplication.primaryScreen()
                avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1920, 1080)
                w = int(avail.width() * 0.8)
                h = int(w / 1.6)
                if h > int(avail.height() * 0.82):
                    h = int(avail.height() * 0.82)
                    w = int(h * 1.6)
                w = min(w, avail.width())
                h = min(h, avail.height())
                self.resize(w, h)
                cfg = self._owner.context.config
                x = cfg.get("window.x")
                y = cfg.get("window.y")
                if x is not None and y is not None:
                    self.move(x, y)
                else:
                    self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)

            def showEvent(self, event):
                super().showEvent(event)
                if self._first_show:
                    self._first_show = False
                    self._apply_geometry()
                    QtCore.QTimer.singleShot(0, self._apply_geometry)
                    QtCore.QTimer.singleShot(60, self._apply_geometry)
                    self._center_on_screen()
                    QtCore.QTimer.singleShot(0, self._center_on_screen)
                    QtCore.QTimer.singleShot(60, self._center_on_screen)

            def _center_on_screen(self):
                screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
                if screen is None:
                    screen = QtGui.QGuiApplication.primaryScreen()
                avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1920, 1080)
                cx = avail.center().x()
                cy = avail.center().y()
                self.move(cx - self.width() // 2, cy - self.height() // 2)

            def closeEvent(self, event):
                if not self._owner._quitting and self._owner.close_to_tray:
                    event.ignore()
                    self.hide()
                    self._owner.tray.tray.showMessage(
                        "YZplan", "程序已在系统托盘后台运行。",
                        QtWidgets.QSystemTrayIcon.Information, 2000,
                    )
                else:
                    self._save_window_geometry()
                    event.accept()

            def resizeEvent(self, event):
                super().resizeEvent(event)

            def _save_window_geometry(self):
                from core.ui_state import window_geometry
                window_geometry().capture(self, "main_window")
                cfg = self._owner.context.config
                cfg.set("window.width", self.width())
                cfg.set("window.height", self.height())
                cfg.set("window.x", self.x())
                cfg.set("window.y", self.y())

            def paintEvent(self, event):
                cfg = self._owner.context.config
                painter = QtGui.QPainter(self)
                painted = _paint_wallpaper_glass(self, painter, cfg)
                painter.end()
                if not painted:
                    super().paintEvent(event)

        self.context = context
        self._quitting = False
        self.close_to_tray = context.config.get("close_to_tray", True)
        self.window = _Window(self)
        self.window.setWindowTitle("YZplan")

        custom_bar = _CustomTitleBar(self.window, self)
        self.window.setTitleBar(custom_bar)

        from core.constants import ICON_PATH
        if os.path.isfile(ICON_PATH):
            self.window.setWindowIcon(QtGui.QIcon(ICON_PATH))

        self.home_tab = None
        self.modules_tab = None
        self.settings_tab = None
        self.about_tab = None
        self.tray = None

    def attach_tray(self, tray):
        self.tray = tray

    def setup(self, home_tab, modules_tab, settings_tab, about_tab):
        self.home_tab = home_tab
        self.modules_tab = modules_tab
        self.settings_tab = settings_tab
        self.about_tab = about_tab

        labels = ("主页", "模块", "程序设置", "关于")
        self.window.addSubInterface(home_tab.widget, FluentIcon.HOME, labels[0])
        self.window.addSubInterface(modules_tab.widget, FluentIcon.APPLICATION, labels[1])
        self.window.addSubInterface(settings_tab.widget, FluentIcon.SETTING, labels[2])
        self.window.addSubInterface(
            about_tab.widget, FluentIcon.INFO, labels[3], position=NavigationItemPosition.BOTTOM
        )
        self._fit_sidebar_width(labels)
        self._hook_sidebar_expand()

    def _hook_sidebar_expand(self):
        """侧边栏展开时主窗口加宽 delta，收起时回退，内容区宽度不变。

        qfluentwidgets 无 expandChanged 信号（API 验证：dir(NavigationInterface)
        仅 expand/setExpandWidth/setMinimumExpandWidth），退路方案：200ms 轮询
        panel.isCollapsed()。delta = 展开宽(expandWidth) - 收起宽(48)。
        """
        if getattr(self, "_sidebar_timer", None) is not None:
            self._sidebar_timer.stop()
        self._sidebar_expanded = None
        self._sidebar_delta = 0
        self._sidebar_timer = QtCore.QTimer(self.window)
        self._sidebar_timer.setInterval(200)
        self._sidebar_timer.timeout.connect(self._poll_sidebar_expand)
        self._sidebar_timer.start()

    def _poll_sidebar_expand(self):
        nav = self.window.navigationInterface
        panel = nav.panel
        try:
            expanded = not panel.isCollapsed()
        except RuntimeError:
            return
        if self._sidebar_expanded is None:
            # 首帧仅记录基线，不调整窗口：否则会把「初始状态」误判为一次
            # 状态切换，导致启动后 0.2s 窗口被无故加宽/收窄 delta。
            self._sidebar_expanded = expanded
            return
        if expanded == self._sidebar_expanded:
            return
        self._sidebar_expanded = expanded
        if self._sidebar_delta == 0:
            self._sidebar_delta = max(0, int(getattr(panel, "expandWidth", 0)) - 48)
        if self._sidebar_delta <= 0:
            return
        if expanded:
            self.window.resize(self.window.width() + self._sidebar_delta, self.window.height())
        else:
            self.window.resize(self.window.width() - self._sidebar_delta, self.window.height())

    def _fit_sidebar_width(self, labels):
        font = QtGui.QFont("Microsoft YaHei", 9)
        metric = QtGui.QFontMetrics(font)
        longest = max(labels, key=lambda t: metric.horizontalAdvance(t))
        text_w = metric.horizontalAdvance(longest)
        icon_w = 36
        padding = 44
        total = int(icon_w + text_w + padding)
        total = max(total, 140)
        try:
            self.window.navigationInterface.setExpandWidth(total)
        except Exception:
            pass

    def apply_wallpaper(self):
        self.window.update()

    def show(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def hide(self):
        self.window.hide()

    def quit(self):
        self._quitting = True
        from ui.module_pages import close_module_pages
        close_module_pages()
        self.window.close()
        self.context.app.quit()
