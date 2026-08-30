"""全局主题：统一调控 qfluentwidgets 与普通 Qt 组件的浅色/深色，支持壁纸与毛玻璃。"""

import os

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_wallpaper_pixmap = None


def resolve_dark(mode):
    """mode: auto / light / dark -> boolean dark"""
    if mode == "dark":
        return True
    if mode == "light":
        return False
    from qfluentwidgets import Theme, qconfig
    return qconfig.theme is Theme.DARK


def load_wallpaper(path):
    global _wallpaper_pixmap
    if path and os.path.isfile(path):
        _wallpaper_pixmap = QtGui.QPixmap(path)
        if _wallpaper_pixmap.isNull():
            _wallpaper_pixmap = None
    else:
        _wallpaper_pixmap = None
    return _wallpaper_pixmap


def get_wallpaper():
    return _wallpaper_pixmap


_BASE_FONT_SIZE = 9


def current_font_scale():
    return ConfigHolder.scale


class ConfigHolder:
    scale = 1.0
    families = ["Microsoft YaHei", "Segoe UI", "PingFang SC"]


def apply_font_scale(scale):
    """按比例缩放全局基础字号（默认 9pt）。返回实际采用的 scale。"""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 1.0
    scale = max(0.7, min(1.6, scale))
    ConfigHolder.scale = scale
    from PySide6.QtGui import QFont
    from .qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        return scale
    f = QtGui.QFont()
    f.setFamily(ConfigHolder.families[0])
    f.setPointSizeF(_BASE_FONT_SIZE * scale)
    app.setFont(f)
    from qfluentwidgets import setFont, setFontFamilies
    setFontFamilies(ConfigHolder.families)
    for w in app.allWidgets():
        try:
            w.update()
        except Exception:
            pass
    return scale


_WP_CACHE = {}


def _blur_pixmap(pixmap, radius=30):
    """对 pixmap 应用高斯模糊，返回新 QPixmap。"""
    if pixmap.isNull() or radius <= 0:
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


_WP_GLASS_CACHE = {}


def paint_wallpaper_glass(widget, painter, cfg):
    """在任意 widget 上绘制壁纸背景，支持毛玻璃(高斯模糊)。

    与主窗口视觉一致：acrylic==True 时对壁纸做高斯模糊并以较低不透明度绘制，
    否则清晰绘制；两者都叠加深色遮罩保证前景可读。返回是否绘制成功。
    """
    wp_path = cfg.get("ui.wallpaper", "")
    if not wp_path or not os.path.isfile(wp_path):
        return False
    sz = widget.size()
    if sz.width() <= 0 or sz.height() <= 0:
        return False
    acrylic = cfg.get("ui.acrylic", False)
    radius = cfg.get("ui.acrylic_blur_radius", 35)
    glass_opacity = cfg.get("ui.acrylic_opacity", 0.7)
    wallpaper_opacity = cfg.get("ui.wallpaper_opacity", 0.35)

    key = ("glass", wp_path, sz.width(), sz.height(), acrylic, radius,
           glass_opacity, wallpaper_opacity)
    cached = _WP_GLASS_CACHE.get(key)
    if cached is None:
        raw = QtGui.QPixmap(wp_path)
        if raw.isNull():
            return False
        scaled = raw.scaled(sz, QtCore.Qt.KeepAspectRatioByExpanding,
                            QtCore.Qt.SmoothTransformation)
        if acrylic and radius > 0:
            scaled = _blur_pixmap(scaled, radius)
        cached = scaled
        _WP_GLASS_CACHE[key] = cached
        if len(_WP_GLASS_CACHE) > 24:
            _WP_GLASS_CACHE.clear()

    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    painter.setOpacity(wallpaper_opacity if not acrylic else wallpaper_opacity * glass_opacity)
    wp_rect = cached.rect()
    target = QtCore.QRect(
        (widget.width() - wp_rect.width()) // 2,
        (widget.height() - wp_rect.height()) // 2,
        wp_rect.width(), wp_rect.height(),
    )
    painter.drawPixmap(target, cached)
    # 遮罩需以完整不透明度绘制，避免被壁纸的不透明度二次削弱
    painter.setOpacity(1.0)
    overlay_alpha = 80 if acrylic else 140
    overlay = QtGui.QColor(30, 30, 30, int(overlay_alpha * (1 - wallpaper_opacity)))
    painter.fillRect(widget.rect(), overlay)
    return True


def paint_wallpaper(widget, painter, cfg):
    """在主窗口/对话框上绘制当前壁纸背景，视觉与主窗口一致。

    widget: 待绘制背景的 QWidget；painter: 已打开的 QPainter(widget)。
    结果按 widget 尺寸缓存，避免重复缩放。
    """
    wp_path = cfg.get("ui.wallpaper", "")
    if not wp_path or not os.path.isfile(wp_path):
        return False
    sz = widget.size()
    key = (wp_path, sz.width(), sz.height(), cfg.get("ui.acrylic", False), cfg.get("ui.wallpaper_opacity", 0.35))
    cached = _WP_CACHE.get(key)
    if cached is None:
        raw = QtGui.QPixmap(wp_path)
        if raw.isNull():
            return False
        scaled = raw.scaled(sz, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        cached = scaled
        _WP_CACHE[key] = cached
        if len(_WP_CACHE) > 24:
            _WP_CACHE.clear()
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    opacity = cfg.get("ui.wallpaper_opacity", 0.35)
    painter.setOpacity(opacity)
    wp_rect = cached.rect()
    target = QtCore.QRect(
        (widget.width() - wp_rect.width()) // 2,
        (widget.height() - wp_rect.height()) // 2,
        wp_rect.width(), wp_rect.height(),
    )
    painter.drawPixmap(target, cached)
    # 遮罩需以完整不透明度绘制，避免被壁纸的不透明度二次削弱
    painter.setOpacity(1.0)
    overlay = QtGui.QColor(30, 30, 30, int(140 * (1 - opacity)))
    painter.fillRect(widget.rect(), overlay)
    return True


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
        pal = QtWidgets.QApplication.style().standardPalette()

    app.setPalette(pal)
    for w in QtWidgets.QApplication.allWidgets():
        try:
            w.update()
        except Exception:
            pass
    return dark


def apply_global_stylesheet(acrylic=False, dark=None):
    """全局 QSS：卡片圆角、滚动条、按钮、输入框等，适配浅色/深色。"""
    if dark is None:
        dark = resolve_dark("auto")

    if dark:
        _apply_dark_sheet(acrylic)
    else:
        _apply_light_sheet(acrylic)


def _apply_dark_sheet(acrylic):
    bg_alpha = "rgba(30,30,30,0.65)" if acrylic else "rgba(30,30,30,0.92)"

    sheet = f"""
    QWidget#modules_tab, QWidget#home_tab, QWidget#settings_tab, QWidget#about_tab {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
    }}

    QListWidget {{
        background: {bg_alpha};
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: rgba(0,120,215,0.35);
    }}
    QListWidget::item:hover {{
        background: rgba(255,255,255,0.06);
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 8px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        min-height: 30px;
        background: rgba(255,255,255,0.12);
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(255,255,255,0.22);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QPushButton {{
        background: rgba(60,60,60,0.80);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 6px;
        padding: 5px 14px;
        color: #e0e0e0;
    }}
    QPushButton:hover {{
        background: rgba(80,80,80,0.90);
        border: 1px solid rgba(255,255,255,0.15);
    }}
    QPushButton:pressed {{
        background: rgba(45,45,45,0.95);
    }}

    QLineEdit {{
        background: rgba(40,40,40,0.85);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 6px;
        padding: 5px 10px;
        color: #e8e8e8;
        selection-background-color: rgba(0,120,215,0.4);
    }}
    QLineEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QComboBox {{
        background: rgba(50,50,50,0.85);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 6px;
        padding: 4px 10px;
        color: #e0e0e0;
    }}

    QFrame {{
        background: transparent;
    }}

    QCheckBox {{
        background: transparent;
        color: #e0e0e0;
    }}

    QToolButton {{
        background: transparent;
        border: none;
    }}

    QMenu {{
        background: rgba(42,42,42,0.96);
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
        color: #e0e0e0;
    }}
    QMenu::item:selected {{
        background: rgba(0,120,215,0.35);
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(255,255,255,0.08);
        margin: 4px 8px;
    }}

    QMessageBox {{
        background: rgba(36,36,36,0.95);
    }}

    QDialog {{
        background: rgba(36,36,36,0.95);
    }}

    QFileDialog {{
        background: rgba(36,36,36,0.95);
    }}
    """

    QtWidgets.QApplication.instance().setStyleSheet(sheet)


def _apply_light_sheet(acrylic):
    bg_alpha = "rgba(245,245,245,0.65)" if acrylic else "rgba(245,245,245,0.92)"

    sheet = f"""
    QWidget#modules_tab, QWidget#home_tab, QWidget#settings_tab, QWidget#about_tab {{
        background: transparent;
    }}

    QLabel {{
        background: transparent;
    }}

    QListWidget {{
        background: {bg_alpha};
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: rgba(0,120,215,0.25);
    }}
    QListWidget::item:hover {{
        background: rgba(0,0,0,0.04);
    }}

    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        width: 8px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        min-height: 30px;
        background: rgba(0,0,0,0.12);
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: rgba(0,0,0,0.22);
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QPushButton {{
        background: rgba(240,240,240,0.90);
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 6px;
        padding: 5px 14px;
        color: #2c2c2c;
    }}
    QPushButton:hover {{
        background: rgba(230,230,230,0.95);
        border: 1px solid rgba(0,0,0,0.15);
    }}
    QPushButton:pressed {{
        background: rgba(210,210,210,0.95);
    }}

    QLineEdit {{
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 6px;
        padding: 5px 10px;
        color: #1a1a1a;
        selection-background-color: rgba(0,120,215,0.3);
    }}
    QLineEdit:focus {{
        border: 1px solid rgba(0,120,215,0.6);
    }}

    QComboBox {{
        background: rgba(255,255,255,0.85);
        border: 1px solid rgba(0,0,0,0.12);
        border-radius: 6px;
        padding: 4px 10px;
        color: #2c2c2c;
    }}

    QFrame {{
        background: transparent;
    }}

    QCheckBox {{
        background: transparent;
        color: #2c2c2c;
    }}

    QToolButton {{
        background: transparent;
        border: none;
    }}

    QMenu {{
        background: rgba(252,252,252,0.96);
        border: 1px solid rgba(0,0,0,0.10);
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
        color: #2c2c2c;
    }}
    QMenu::item:selected {{
        background: rgba(0,120,215,0.18);
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(0,0,0,0.08);
        margin: 4px 8px;
    }}

    QMessageBox {{
        background: rgba(252,252,252,0.95);
    }}

    QDialog {{
        background: rgba(252,252,252,0.95);
    }}

    QFileDialog {{
        background: rgba(252,252,252,0.95);
    }}
    """

    QtWidgets.QApplication.instance().setStyleSheet(sheet)
