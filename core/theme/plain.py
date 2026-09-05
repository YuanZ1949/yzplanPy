"""普通壁纸绘制。"""
import os
from core.qt_bootstrap import import_qt
from .blur import _WP_CACHE
_, QtCore, QtGui, QtWidgets = import_qt()

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
