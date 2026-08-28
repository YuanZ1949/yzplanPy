import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:\\Windows\\Fonts")

from core.qt_bootstrap import import_qt

PySide6, QtCore, QtGui, QtWidgets = import_qt()
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setFont(QtGui.QFont("Microsoft YaHei", 9))

# 先建 QApplication 再导入 qfluentwidgets/UI 模块
from core.config import AppConfig
from core.constants import CONFIG_PATH
from modules.registry import ModuleContext, ModuleRegistry
from ui.mainwindow import MainWindow
from ui.home_tab import HomeTab
from ui.modules_tab import ModulesTab
from ui.settings_tab import SettingsTab
from ui.about_tab import AboutTab

config = AppConfig()
context = ModuleContext(config=config, host_window=None, app=app)
context.registry = ModuleRegistry(context)
m = MainWindow(context)
m.setup(HomeTab(context), ModulesTab(context), SettingsTab(context), AboutTab(context))
print("nav pages:", m.window.stackedWidget.count())
print("modules found:", [(x.id, x.name) for x in context.registry.all()])
print("enabled:", [x.id for x in context.registry.enabled()])
print("SMOKE OK")