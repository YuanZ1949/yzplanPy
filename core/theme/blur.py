"""壁纸模糊与缓存。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

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
