"""毛玻璃壁纸绘制。"""
import os
from core.qt_bootstrap import import_qt
from .blur import _blur_pixmap
_, QtCore, QtGui, QtWidgets = import_qt()

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
