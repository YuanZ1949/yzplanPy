"""home_tab.handle: 缩放手柄（_Handle），拖拽卡片边缘/角落来缩放。"""
from core.qt_bootstrap import import_qt
from .constants import _MIN_H, _MIN_W
_, QtCore, QtGui, QtWidgets = import_qt()

class _Handle(QtWidgets.QGraphicsRectItem):
    """拖拽卡片边缘/角落来缩放。只负责缩放，不负责移动。"""

    _CURSOR = {
        "r": QtGui.Qt.SizeHorCursor,
        "b": QtGui.Qt.SizeVerCursor,
        "c": QtGui.Qt.SizeFDiagCursor,
    }

    def __init__(self, owner, proxy, card, mode, cid):
        s = 20
        super().__init__(-s // 2, -s // 2, s, s)
        self._owner = owner
        self._proxy = proxy
        self._card = card
        self._cid = cid
        self._mode = mode
        self.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 0)))
        self.setPen(QtCore.Qt.NoPen)
        self.setCursor(self._CURSOR[mode])
        self.setZValue(200)
        self.setAcceptHoverEvents(True)
        self._hovering = False
        self._active = False

    def paint(self, painter, option, widget):
        if self._hovering or self._active:
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            from core.theme import resolve_dark
            dark = resolve_dark("auto")
            c = QtGui.QColor(0, 120, 215, 100) if dark else QtGui.QColor(0, 120, 215, 70)
            painter.setBrush(c)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(self.rect())

    def hoverEnterEvent(self, event):
        self._hovering = True
        self.update()

    def hoverLeaveEvent(self, event):
        self._hovering = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._active = True
            self._start = event.scenePos()
            self._orig_w = self._card.width()
            self._orig_h = self._card.height()
            self._owner._dragging_cid = self._cid
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._active:
            return
        if self._mode in ("r", "c"):
            d = event.scenePos().x() - self._start.x()
            new_w = max(_MIN_W, int(self._orig_w + d))
            if new_w != self._card.width():
                self._card.setFixedSize(new_w, self._card.height())
                self._owner._saved[self._cid] = {
                    **self._owner._saved.get(self._cid, {}),
                    "width": new_w,
                }
                self._owner._schedule_save()
                self._owner._relayout_all()
        if self._mode in ("b", "c"):
            d = event.scenePos() - self._start
            h = max(_MIN_H, int(self._orig_h + d.y()))
            if h != self._card.height():
                self._card.setFixedHeight(h)
                self._owner._saved[self._cid] = {
                    **self._owner._saved.get(self._cid, {}),
                    "height": h,
                }
                self._owner._update_handles(self._proxy, self._card)
                self._owner._schedule_save()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._active = False
        self._start = None
        if self._owner._dragging_cid == self._cid:
            self._owner._dragging_cid = None
        self.update()
        event.accept()
