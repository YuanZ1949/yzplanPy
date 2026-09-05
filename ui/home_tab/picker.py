"""home_tab.picker: 添加组件弹出面板（_AddPopup/_PickCard）。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, StrongBodyLabel, SubtitleLabel
_, QtCore, QtGui, QtWidgets = import_qt()

class _AddPopup(QtWidgets.QFrame):
    def __init__(self, owner, parent=None):
        super().__init__(parent, QtCore.Qt.Popup)
        self._owner = owner
        self.setObjectName("add_component_popup")

        from core.theme import resolve_dark
        dark = resolve_dark("auto")
        if dark:
            self.setStyleSheet(
                "#add_component_popup { background: rgba(42,42,42,0.96); "
                "border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; }"
            )
        else:
            self.setStyleSheet(
                "#add_component_popup { background: rgba(252,252,252,0.96); "
                "border: 1px solid rgba(0,0,0,0.10); border-radius: 12px; }"
            )

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = SubtitleLabel("添加组件")
        lay.addWidget(title)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(10)

        comps = owner._available_components()
        added = set(owner._order)
        for i, (cid, name) in enumerate(comps):
            card = _PickCard(cid, name, owner.context.registry, self._pick, is_added=(cid in added))
            grid.addWidget(card, i // 3, i % 3)

        lay.addLayout(grid)

        if not comps:
            lay.addWidget(BodyLabel("没有可用的组件"))

        self.adjustSize()

    def _pick(self, cid):
        self._owner._add_component(cid)
        self.close()


class _PickCard(QtWidgets.QFrame):
    def __init__(self, cid, name, registry, on_pick, is_added=False, parent=None):
        super().__init__(parent)
        self.cid = cid
        self._on_pick = on_pick
        self._hover = False
        self._is_added = is_added

        self.setFixedSize(140, 90)
        self.setCursor(QtGui.Qt.PointingHandCursor if not is_added else QtGui.Qt.ForbiddenCursor)
        self.setMouseTracking(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        lay.setAlignment(QtCore.Qt.AlignCenter)

        name_lb = StrongBodyLabel(name)
        name_lb.setAlignment(QtCore.Qt.AlignCenter)
        name_lb.setWordWrap(True)
        lay.addWidget(name_lb)

        mod = registry.get(cid)
        if mod:
            desc = BodyLabel(mod.description)
            desc.setAlignment(QtCore.Qt.AlignCenter)
            desc.setWordWrap(True)
            lay.addWidget(desc, 1)
        if is_added:
            added_lb = BodyLabel("已添加")
            added_lb.setStyleSheet("color: #888; background: transparent;")
            added_lb.setAlignment(QtCore.Qt.AlignCenter)
            lay.addWidget(added_lb)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        from core.theme import resolve_dark
        dark = resolve_dark("auto")

        if self._is_added:
            if dark:
                bg = QtGui.QColor(38, 38, 38, 160)
                border = QtGui.QColor(255, 255, 255, 8)
            else:
                bg = QtGui.QColor(230, 230, 230, 160)
                border = QtGui.QColor(0, 0, 0, 8)
        elif self._hover:
            if dark:
                bg = QtGui.QColor(55, 55, 55, 230)
                border = QtGui.QColor(100, 160, 255, 80)
            else:
                bg = QtGui.QColor(240, 245, 255, 230)
                border = QtGui.QColor(0, 120, 215, 80)
        else:
            if dark:
                bg = QtGui.QColor(42, 42, 42, 200)
                border = QtGui.QColor(255, 255, 255, 14)
            else:
                bg = QtGui.QColor(252, 252, 252, 200)
                border = QtGui.QColor(0, 0, 0, 14)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 10, 10)
        painter.end()

    def enterEvent(self, event):
        if not self._is_added:
            self._hover = True
            self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and not self._is_added:
            self._on_pick(self.cid)
