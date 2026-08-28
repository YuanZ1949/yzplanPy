"""主窗口：Fluent 风格导航界面（主页/模块/设置/关于），支持壁纸背景与毛玻璃，关闭时最小化到托盘。"""
import os
from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon, FluentWindow, NavigationItemPosition

_, QtCore, QtGui, QtWidgets = import_qt()


def _blur_pixmap(pixmap, radius=30):
    if pixmap.isNull():
        return pixmap
    from PySide6.QtWidgets import QGraphicsScene, QGraphicsBlurEffect
    scene = QGraphicsScene()
    item = scene.addPixmap(pixmap)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(radius)
    item.setGraphicsEffect(blur)
    image = QtGui.QImage(pixmap.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    scene.render(painter)
    painter.end()
    return QtGui.QPixmap.fromImage(image)


class MainWindow:
    def __init__(self, context):
        class _Window(FluentWindow):
            def __init__(self, owner):
                super().__init__()
                self._owner = owner
                self._wp_cache = None
                self._wp_cache_path = None
                self._wp_cache_size = None
                self._blurred_cache = None

                from core.ui_state import window_geometry
                restored = window_geometry().apply(self, "main_window")
                if not restored:
                    cfg = owner.context.config
                    w = cfg.get("window.width", 960)
                    h = cfg.get("window.height", 640)
                    self.resize(w, h)
                    x = cfg.get("window.x")
                    y = cfg.get("window.y")
                    if x is not None and y is not None:
                        self.move(x, y)

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
                self._wp_cache = None

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
                wp_path = cfg.get("ui.wallpaper", "")
                if wp_path and QtCore.QFile.exists(wp_path):
                    if self._wp_cache is None or self._wp_cache_path != wp_path or self._wp_cache_size != self.size():
                        raw = QtGui.QPixmap(wp_path)
                        if not raw.isNull():
                            scaled = raw.scaled(
                                self.size(), QtCore.Qt.KeepAspectRatioByExpanding,
                                QtCore.Qt.SmoothTransformation,
                            )
                            acrylic = cfg.get("ui.acrylic", False)
                            if acrylic:
                                self._blurred_cache = _blur_pixmap(scaled, 35)
                            else:
                                self._blurred_cache = None
                            self._wp_cache = scaled
                            self._wp_cache_path = wp_path
                            self._wp_cache_size = self.size()
                        else:
                            self._wp_cache = None
                    if self._wp_cache and not self._wp_cache.isNull():
                        painter = QtGui.QPainter(self)
                        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
                        opacity = cfg.get("ui.wallpaper_opacity", 0.35)
                        acrylic = cfg.get("ui.acrylic", False)
                        if acrylic and self._blurred_cache and not self._blurred_cache.isNull():
                            painter.setOpacity(opacity * 0.7)
                            wp_rect = self._blurred_cache.rect()
                            target_rect = QtCore.QRect(
                                (self.width() - wp_rect.width()) // 2,
                                (self.height() - wp_rect.height()) // 2,
                                wp_rect.width(), wp_rect.height(),
                            )
                            painter.drawPixmap(target_rect, self._blurred_cache)
                            overlay = QtGui.QColor(30, 30, 30, int(80 * (1 - opacity)))
                            painter.fillRect(self.rect(), overlay)
                        else:
                            painter.setOpacity(opacity)
                            wp_rect = self._wp_cache.rect()
                            target_rect = QtCore.QRect(
                                (self.width() - wp_rect.width()) // 2,
                                (self.height() - wp_rect.height()) // 2,
                                wp_rect.width(), wp_rect.height(),
                            )
                            painter.drawPixmap(target_rect, self._wp_cache)
                            overlay = QtGui.QColor(30, 30, 30, int(140 * (1 - opacity)))
                            painter.fillRect(self.rect(), overlay)
                        painter.end()
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

        self.window.addSubInterface(home_tab.widget, FluentIcon.HOME, "主页")
        self.window.addSubInterface(modules_tab.widget, FluentIcon.APPLICATION, "模块")
        self.window.addSubInterface(settings_tab.widget, FluentIcon.SETTING, "程序设置")
        self.window.addSubInterface(
            about_tab.widget, FluentIcon.INFO, "关于", position=NavigationItemPosition.BOTTOM
        )

    def apply_wallpaper(self):
        from core.theme import load_wallpaper
        wp = self.context.config.get("ui.wallpaper", "")
        load_wallpaper(wp)
        self.window._wp_cache = None
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
