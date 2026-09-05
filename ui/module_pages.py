"""模块页面窗口统一管理：每个模块全局只存在一个页面窗口。

“模块选项卡”和“系统托盘”共用同一入口，避免出现两个内容同步的重复窗口。
- frameless=True 的页面（如 RSS）走无边框窗 + FluentTitleBar（设置/更多/最小化/最大化/关闭）
- 其余模块保持原生 QDialog（单行系统标题栏）
"""

from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon, FluentTitleBar, FluentTitleBarButton
from qfluentwidgets.components.widgets.frameless_window import FramelessWindow

_, QtCore, QtGui, QtWidgets = import_qt()

_pages = {}


class _ModuleWindow(FramelessWindow):
    """无边框模块窗口：FluentTitleBar（设置/更多/最小化/最大化/关闭）+ 内容页。"""

    def __init__(self, mod, page, default_size, min_size):
        super().__init__()
        self._module = mod
        self._page = page
        self._geo_mgr = None
        self._geo_key = "module_page_" + mod.id

        # Win11 下 FramelessWindow 默认启用 Mica（毛玻璃）；与 WebEngine 预览共存时
        # 会导致标题栏/背景发黑、窗口闪烁（看起来像"关闭后再开新窗口"）。
        # 改为纯色背景，与主窗口（无壁纸时的底色）保持一致。
        try:
            self.windowEffect.removeBackgroundEffect(self.winId())
        except Exception:
            pass
        self._bg_color = QtWidgets.QApplication.palette().color(QtGui.QPalette.Window)

        self.setWindowTitle(mod.name)
        self.setMinimumSize(*min_size)

        tb = FluentTitleBar(self)
        tb.setFixedHeight(36)  # 单行紧凑标题栏
        # 标题栏定制按钮：设置 + 更多，插入到最小化/最大化/关闭之前
        self.settingsBtn = FluentTitleBarButton(FluentIcon.SETTING, tb)
        self.settingsBtn.setToolTip("模块设置")
        self.settingsBtn.setFixedSize(36, 30)
        self.settingsBtn.clicked.connect(self._open_settings)
        self.moreBtn = FluentTitleBarButton(FluentIcon.MENU, tb)
        self.moreBtn.setToolTip("更多操作")
        self.moreBtn.setFixedSize(36, 30)
        self.moreBtn.clicked.connect(self._open_more)
        tb.buttonLayout.insertWidget(0, self.settingsBtn)
        tb.buttonLayout.insertWidget(1, self.moreBtn)
        self.setTitleBar(tb)
        self.titleBar.raise_()  # 内容区为后添加的兄弟控件，需保证标题栏浮于其上方

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 36, 0, 0)  # 顶部让出 36px 标题栏高度（单行）
        lay.setSpacing(0)
        lay.addWidget(page)

        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        from core.ui_state import window_geometry
        self._geo_mgr = window_geometry()
        self._geo_mgr.apply(self, self._geo_key, default_size=default_size)

    def _open_settings(self):
        cb = getattr(self._page, "_toggle_settings_section", None)
        if cb:
            cb()

    def _open_more(self):
        has_export = hasattr(self._page, "_export_opml")
        has_import = hasattr(self._page, "_import_opml")
        if not has_export and not has_import:
            return
        menu = QtWidgets.QMenu(self.moreBtn)
        if has_export:
            menu.addAction("导出 OPML", self._page._export_opml)
        if has_import:
            menu.addAction("导入 OPML", self._page._import_opml)
        menu.exec(self.moreBtn.mapToGlobal(self.moreBtn.rect().bottomLeft()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        tb = self.titleBar
        tb.move(0, 0)
        tb.resize(self.width(), tb.height())
        tb.raise_()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)

    def closeEvent(self, event):
        if self._geo_mgr is not None:
            self._geo_mgr.capture(self, self._geo_key)
        super().closeEvent(event)


def open_module_page(mod, parent=None):
    """打开模块页面窗口（每个模块全局单例）。

    已打开则激活已有窗口，否则创建后显示。返回窗口对象（失败返回 None）。
    """
    existing = _pages.get(mod.id)
    if existing is not None:
        try:
            if existing.isVisible():
                existing.raise_()
                existing.activateWindow()
                return existing
        except RuntimeError:
            pass
        _pages.pop(mod.id, None)

    page = mod.create_page(parent)
    if page is None:
        return None
    frameless = bool(getattr(page, "frameless", False))

    screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
    if screen is None:
        screen = QtGui.QGuiApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1280, 800)
    default_w = max(900, int(avail.width() * 0.8))
    default_h = max(620, int(avail.height() * 0.8))

    if frameless:
        dlg = _ModuleWindow(mod, page, (default_w, default_h), (940, 580))
    else:
        min_size = (760, 560)
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle(mod.name)
        dlg.setMinimumSize(*min_size)
        dlg.setWindowModality(QtCore.Qt.NonModal)
        geometry_key = "module_page_" + mod.id
        from core.ui_state import window_geometry
        geometry = window_geometry()
        geometry.apply(dlg, geometry_key, default_size=(default_w, default_h))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, geometry_key))
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)

    _pages[mod.id] = dlg
    dlg.destroyed.connect(
        lambda _o, m=mod.id, d=dlg: (
            _pages.pop(m, None) if _pages.get(m) is d else None
        )
    )
    dlg.show()
    return dlg