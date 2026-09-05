"""应用主题与全局 palette。"""
from core.qt_bootstrap import import_qt
from .base import resolve_dark
_, QtCore, QtGui, QtWidgets = import_qt()

def apply_app_theme(mode="auto"):
    """应用主题到 qfluentwidgets 与全局 palette。"""
    from qfluentwidgets import Theme, setTheme

    dark = resolve_dark(mode)
    setTheme(Theme.DARK if dark else Theme.LIGHT)

    app = QtWidgets.QApplication.instance()
    if app is None:
        return dark

    if dark:
        pal = QtGui.QPalette()
        bg = QtGui.QColor(30, 30, 30)
        base = QtGui.QColor(36, 36, 36)
        txt = QtGui.QColor(240, 240, 240)
        pal.setColor(QtGui.QPalette.Window, bg)
        pal.setColor(QtGui.QPalette.WindowText, txt)
        pal.setColor(QtGui.QPalette.Base, base)
        pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(44, 44, 44))
        pal.setColor(QtGui.QPalette.Text, txt)
        pal.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 255, 255))
        pal.setColor(QtGui.QPalette.Button, QtGui.QColor(42, 42, 42))
        pal.setColor(QtGui.QPalette.ButtonText, txt)
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(0, 120, 215))
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
        pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(140, 140, 140))
    else:
        # 不能直接用 style().standardPalette()：不同 Windows 样式/配色方案下
        # Window 可能是经典米色(#d4d0c8)，导致对话框/透明页面露出米色底。
        # 显式使用中性浅色调色板，保证主题统一。
        pal = QtGui.QPalette()
        bg = QtGui.QColor(255, 255, 255)
        base = QtGui.QColor(255, 255, 255)
        txt = QtGui.QColor(26, 26, 26)
        pal.setColor(QtGui.QPalette.Window, bg)
        pal.setColor(QtGui.QPalette.WindowText, txt)
        pal.setColor(QtGui.QPalette.Base, base)
        pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(244, 244, 244))
        pal.setColor(QtGui.QPalette.Text, txt)
        pal.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 255, 255))
        pal.setColor(QtGui.QPalette.Button, QtGui.QColor(243, 243, 243))
        pal.setColor(QtGui.QPalette.ButtonText, txt)
        pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(0, 120, 215))
        pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
        pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(150, 150, 150))

    # 显式设置 Inactive/Disabled 组文字颜色：新建的 QPalette 这些组默认是白/黑
    # 占位，QStyleSheetStyle 画未选中 tab 标签等会取 Disabled 组，导致文字与
    # 背景同色而不可见。
    dis_txt = QtGui.QColor(120, 120, 120) if dark else QtGui.QColor(160, 160, 160)
    dis_bg = QtGui.QColor(52, 52, 52) if dark else QtGui.QColor(250, 250, 250)
    dis_hl = QtGui.QColor(210, 210, 210) if dark else QtGui.QColor(245, 245, 245)
    for grp in (QtGui.QPalette.ColorGroup.Inactive, QtGui.QPalette.ColorGroup.Disabled):
        pal.setColor(grp, QtGui.QPalette.Window, dis_bg)
        pal.setColor(grp, QtGui.QPalette.WindowText, dis_txt)
        pal.setColor(grp, QtGui.QPalette.Base, dis_bg)
        pal.setColor(grp, QtGui.QPalette.Text, dis_txt)
        pal.setColor(grp, QtGui.QPalette.Button, dis_bg)
        pal.setColor(grp, QtGui.QPalette.ButtonText, dis_txt)
        pal.setColor(grp, QtGui.QPalette.HighlightedText, dis_hl)

    app.setPalette(pal)
    for w in QtWidgets.QApplication.allWidgets():
        try:
            w.update()
        except Exception:
            pass
    return dark
