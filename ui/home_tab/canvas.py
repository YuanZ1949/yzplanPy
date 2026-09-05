"""home_tab.canvas: QGraphicsView 画布视图（_CanvasView）。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

class _CanvasView(QtWidgets.QGraphicsView):
    def __init__(self, scene, owner=None):
        super().__init__(scene)
        self._owner = owner

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_scene()
        if self._owner:
            self._owner._relayout_timer.start()

    def _sync_scene(self):
        s = self.scene()
        if not s:
            return
        br = s.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        vr = self.viewport().rect()
        s.setSceneRect(br.united(QtCore.QRectF(0, 0, vr.width(), vr.height())))

    def wheelEvent(self, event):
        if event.modifiers() == QtCore.Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)
