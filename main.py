"""YZplan 程序入口。"""
import logging
import os
import sys

from core.qt_bootstrap import import_qt

PySide6, QtCore, QtGui, QtWidgets = import_qt()

from core.constants import APP_ID, DATA_DIR


def _load_translations(app):
    from core.constants import TRANSLATION_DIR
    import glob
    qms = sorted(glob.glob(os.path.join(TRANSLATION_DIR, "*.qm")))
    for qm in qms:
        translator = QtCore.QTranslator(app)
        if translator.load(qm):
            app.installTranslator(translator)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    from core.logger import setup_logger
    setup_logger()
    logger = logging.getLogger("core")
    logger.info("YZplan 启动中...")

    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("YZplan")
        except Exception:
            pass

    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 抑制 Qt 平台层字体警告（DirectWrite 找不到 MS Sans Serif）
    _original_handler = None

    def _qt_msg_handler(msg_type, context, message):
        if "MS Sans Serif" in message or "CreateFontFaceFromHDC" in message:
            return
        if _original_handler:
            _original_handler(msg_type, context, message)

    _original_handler = QtCore.qInstallMessageHandler(_qt_msg_handler)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("YZplan")
    app.setQuitOnLastWindowClosed(False)

    # 先建 QApplication 再导入 qfluentwidgets/UI 模块（图标字体注册依赖 GUI 实例，否则触发字体警告）
    # 抑制 qfluentwidgets Tips 提示（stdout 重定向）
    _old_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        from core.config import AppConfig
        from core.singleinstance import SingleInstance
        from core.theme import apply_app_theme, apply_global_stylesheet, load_wallpaper
        from core.tray import Tray
        from modules.registry import ModuleContext, ModuleRegistry
        from ui.mainwindow import MainWindow
        from ui.home_tab import HomeTab
        from ui.modules_tab import ModulesTab
        from ui.settings_tab import SettingsTab
        from ui.about_tab import AboutTab
    finally:
        sys.stdout.close()
        sys.stdout = _old_stdout

    app.setFont(QtGui.QFont("Microsoft YaHei", 9))
    from qfluentwidgets import setFontFamilies
    setFontFamilies(["Microsoft YaHei", "Segoe UI", "PingFang SC"])

    _load_translations(app)

    si = SingleInstance(DATA_DIR, APP_ID)
    if not si.try_acquire():
        print("YZplan 已有一个实例在运行。")
        return 0

    config = AppConfig()
    apply_app_theme(config.get("ui.theme", "auto"))
    apply_global_stylesheet(config.get("ui.acrylic", False))
    load_wallpaper(config.get("ui.wallpaper", ""))
    context = ModuleContext(config=config, host_window=None, app=app)
    context.registry = ModuleRegistry(context)

    mw = MainWindow(context)
    context.host_window = mw
    mw.setup(HomeTab(context), ModulesTab(context), SettingsTab(context), AboutTab(context))

    tray = Tray(mw.window, on_show_home=mw.show, on_quit=mw.quit, context=context)
    mw.attach_tray(tray)
    context.tray = tray

    context.registry.start_enabled()

    if not config.get("window.start_hidden", False):
        mw.show()

    exit_code = app.exec()
    context.registry.stop_all()
    si.release()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())