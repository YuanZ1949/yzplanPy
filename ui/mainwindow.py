"""主窗口：Fluent 风格导航界面（主页/模块/设置/关于），支持壁纸背景与毛玻璃，关闭时最小化到托盘。"""
import os
from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon, FluentWindow, NavigationItemPosition
from core.theme import paint_wallpaper_glass as _paint_wallpaper_glass

_, QtCore, QtGui, QtWidgets = import_qt()


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
                    # qframelesswindow 的原生层最早启动在事件循环里把窗口缩回初始尺寸，
                    # 这里首次显示时同步+延迟兜底重放几何，避免出现“默认小窗口”
                    self._apply_geometry()
                    QtCore.QTimer.singleShot(0, self._apply_geometry)
                    QtCore.QTimer.singleShot(60, self._apply_geometry)
                    # 无论是否恢复历史位置，首次显示都把窗口画面中心放到屏幕中央
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
        self.window.close()
        self.context.app.quit()
