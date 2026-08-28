"""模块选项卡：正方形方块卡片网格，内含名称/描述/开关，点击打开模块页面。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, StrongBodyLabel, SwitchButton

_, QtCore, QtGui, QtWidgets = import_qt()

_CARD_SIZE = 170
_CARD_RADIUS = 16


class _ModuleCard(QtWidgets.QFrame):
    """正方形模块卡片：居中名称+描述+开关。"""

    def __init__(self, mod, registry, on_open_page, on_toggle, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.registry = registry
        self._on_open_page = on_open_page
        self._on_toggle = on_toggle
        self._hover = False

        self.setObjectName(f"module_card_{mod.id}")
        self.setFixedSize(_CARD_SIZE, _CARD_SIZE)
        self.setCursor(QtGui.Qt.PointingHandCursor)
        self.setMouseTracking(True)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(4)
        lay.setAlignment(QtCore.Qt.AlignCenter)

        self.lb_name = StrongBodyLabel(mod.name)
        self.lb_name.setAlignment(QtCore.Qt.AlignCenter)
        self.lb_name.setWordWrap(True)
        lay.addWidget(self.lb_name)

        self.lb_desc = BodyLabel(mod.description)
        self.lb_desc.setAlignment(QtCore.Qt.AlignCenter)
        self.lb_desc.setWordWrap(True)
        lay.addWidget(self.lb_desc, 1)

        self.sw = SwitchButton()
        self.sw.setOnText("开")
        self.sw.setOffText("关")
        self.sw.setChecked(self.registry.is_enabled(mod.id))
        self.sw.checkedChanged.connect(self._sw_changed)
        sw_row = QtWidgets.QHBoxLayout()
        sw_row.setAlignment(QtCore.Qt.AlignCenter)
        sw_row.addWidget(self.sw)
        lay.addLayout(sw_row)

    def _sw_changed(self, on):
        self._on_toggle(self.mod, on)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        from core.theme import resolve_dark
        dark = resolve_dark("auto")

        if dark:
            bg = QtGui.QColor(55, 55, 55, 230) if self._hover else QtGui.QColor(40, 40, 40, 200)
            border = QtGui.QColor(100, 160, 255, 60) if self._hover else QtGui.QColor(255, 255, 255, 14)
        else:
            bg = QtGui.QColor(255, 255, 255, 245) if self._hover else QtGui.QColor(245, 245, 245, 230)
            border = QtGui.QColor(0, 120, 215, 80) if self._hover else QtGui.QColor(0, 0, 0, 15)

        rect = self.rect().adjusted(1, 1, -1, -1)

        if self._hover:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(80, 140, 255, 20) if dark else QtGui.QColor(0, 120, 215, 15))
            painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), _CARD_RADIUS + 2, _CARD_RADIUS + 2)

        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
        painter.end()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self.sw.geometry().contains(event.pos()):
                return
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self.sw.geometry().contains(event.pos()):
                return
            self._on_open_page(self.mod)
            event.accept()


class ModulesTab:
    def __init__(self, context):
        self.context = context
        self.registry = context.registry
        self.cards = []
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("modules_tab")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(16, 16, 16, 16)

        header = StrongBodyLabel("模块管理")
        layout.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.grid_widget = QtWidgets.QWidget()
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 4, 0, 0)
        self.grid_layout.setSpacing(14)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll, 1)

        self._rebuild()

    def _rebuild(self):
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()

        mods = self.registry.all()
        cols = 4
        for i, mod in enumerate(mods):
            card = _ModuleCard(
                mod, self.registry,
                self._open_page, self._on_toggle,
            )
            self.cards.append(card)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
        self.grid_layout.setRowStretch((len(mods) // cols) + 1, 1)

    def _on_toggle(self, mod, enabled):
        self.context.config.set_module_enabled(mod.id, enabled)
        if enabled:
            try:
                mod.start()
            except Exception:
                pass
        else:
            try:
                mod.stop()
            except Exception:
                pass

    def _open_page(self, mod):
        page = mod.create_page(self.widget)
        if page is None:
            QtWidgets.QMessageBox.information(
                self.widget, mod.name, "该模块没有独立页面。"
            )
            return
        dlg = QtWidgets.QDialog(self.widget)
        dlg.setWindowTitle(mod.name)
        dlg.setMinimumSize(740, 560)
        from core.ui_state import window_geometry
        geometry = window_geometry()
        geometry.apply(dlg, "module_page_" + mod.id, default_size=(740, 560))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(page)
        dlg.finished.connect(lambda *_: geometry.capture(dlg, "module_page_" + mod.id))
        dlg.exec()
