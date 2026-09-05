"""home_tab.proxy: 卡片代理（_Proxy），只负责拖拽移动。"""
from core.qt_bootstrap import import_qt
from .constants import _DRAG_THRESHOLD
_, QtCore, QtGui, QtWidgets = import_qt()

class _Proxy(QtWidgets.QGraphicsProxyWidget):
    """只负责拖拽移动。"""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self._dragging = False
        self._drag_start = None
        self._press_scene_pos = None

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionChange:
            self._owner._schedule_save()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._press_scene_pos = event.scenePos()
            self._dragging = False
            self._drag_start = None
        super().mousePressEvent(event)

    def _mark_dragging(self, cid):
        owner = self._owner
        if owner is not None and hasattr(owner, "_dragging_cid"):
            owner._dragging_cid = cid

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.NoButton:
            super().mouseMoveEvent(event)
            return
        if self._press_scene_pos is not None and not self._dragging:
            if (event.scenePos() - self._press_scene_pos).manhattanLength() >= _DRAG_THRESHOLD:
                self._dragging = True
                self._drag_start = event.scenePos() - self.pos()
                self.setZValue(100)
                cid = self._owner._cid_of(self) if hasattr(self._owner, "_cid_of") else None
                self._mark_dragging(cid)
        if self._dragging and self._drag_start is not None:
            self.setPos(event.scenePos() - self._drag_start)
            self._owner._highlight_swap(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_scene_pos = None
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            self.setZValue(0)
            self._mark_dragging(None)
            self._owner._finish_swap(self)
            self._owner._relayout_all()
            event.accept()
            return
        self._drag_start = None
        super().mouseReleaseEvent(event)
