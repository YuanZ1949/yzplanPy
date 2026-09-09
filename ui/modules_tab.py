"""模块选项卡：正方形方块卡片网格，内含名称/描述/开关，点击打开模块页面。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, StrongBodyLabel, SwitchButton

_, QtCore, QtGui, QtWidgets = import_qt()

_CARD_SIZE = 170
_CARD_RADIUS = 16
_DRAG_THRESHOLD = 8  # 像素：超过才视为拖拽，否则仍是点击打开
_MIME_MODULE = "application/x-yzplan-module"


def _swap_order(order, src_id, dst_id):
    """纯函数：把 src_id 移动到 dst_id 所在槽位，返回新顺序列表（不修改入参）。"""
    if src_id not in order or dst_id not in order:
        return list(order)
    i, j = order.index(src_id), order.index(dst_id)
    if i == j:
        return list(order)
    out = list(order)
    out.pop(i)
    out.insert(j, src_id)
    return out


class _GridResizeWatcher(QtCore.QObject):
    """监听卡片网格容器尺寸变化，列数变化时触发重建。"""

    def __init__(self, on_resize, parent=None):
        super().__init__(parent)
        self._on_resize = on_resize

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Resize:
            self._on_resize()
        return super().eventFilter(obj, event)


class _ModuleGrid(QtWidgets.QWidget):
    """可接收模块卡片拖放的网格容器。"""

    def __init__(self, on_drop, parent=None):
        super().__init__(parent)
        self._on_drop = on_drop
        self.setAcceptDrops(True)

    def _card_at(self, pos):
        w = self.childAt(pos)
        while w is not None and not isinstance(w, _ModuleCard):
            w = w.parentWidget()
        return w

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_MODULE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_MODULE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_MODULE):
            event.ignore()
            return
        src_id = bytes(event.mimeData().data(_MIME_MODULE)).decode("utf-8", "replace")
        dst_card = self._card_at(event.position().toPoint())
        if dst_card is None:
            event.ignore()  # 拖到空白处：不崩溃、不移动
            return
        self._on_drop(src_id, dst_card.mod.id)
        event.acceptProposedAction()


class _ModuleCard(QtWidgets.QFrame):
    """正方形模块卡片：居中名称+描述+开关。"""

    def __init__(self, mod, registry, on_open_page, on_toggle, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.registry = registry
        self._on_open_page = on_open_page
        self._on_toggle = on_toggle
        self._hover = False
        self._press_pos = None
        self._drag_started = False

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
            self._press_pos = event.pos()
            self._drag_started = False
            event.accept()

    def mouseMoveEvent(self, event):
        if (
            self._press_pos is not None
            and not self._drag_started
            and (event.buttons() & QtCore.Qt.LeftButton)
            and (event.pos() - self._press_pos).manhattanLength() > _DRAG_THRESHOLD
        ):
            self._drag_started = True
            mime = QtCore.QMimeData()
            mime.setData(_MIME_MODULE, self.mod.id.encode("utf-8"))
            drag = QtGui.QDrag(self)
            drag.setMimeData(mime)
            drag.exec(QtCore.Qt.MoveAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            if self.sw.geometry().contains(event.pos()):
                return
            if self._drag_started:
                return  # 刚完成拖拽，不触发打开
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

        self.grid_widget = _ModuleGrid(self._on_drop)
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 4, 0, 0)
        self.grid_layout.setSpacing(14)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll, 1)

        # 卡片列数随网格宽度自适应：仅当列数实际变化时才重建
        self._cols = 0
        self._resize_watcher = _GridResizeWatcher(self._on_grid_resize)
        self.grid_widget.installEventFilter(self._resize_watcher)

        self._rebuild()

    def _calc_cols(self):
        spacing = self.grid_layout.spacing()
        return max(1, (self.grid_widget.width() + spacing) // (_CARD_SIZE + spacing))

    def _on_grid_resize(self):
        cols = self._calc_cols()
        if cols != self._cols:
            self._rebuild()

    def _rebuild(self):
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()

        mods = self.registry.all()
        # 应用持久化顺序（modules.order）：拖拽排序在列数变化重建后仍保留
        cfg = getattr(self.context, "config", None)
        order = cfg.get("modules.order", None) if cfg is not None else None
        if order:
            by_id = {m.id: m for m in mods}
            ordered = [by_id[i] for i in order if i in by_id]
            rest = [m for m in mods if m.id not in order]
            mods = ordered + rest

        cols = self._calc_cols()
        self._cols = cols
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

    def _on_drop(self, src_id, dst_id):
        """拖放交换：把 src 卡片移到 dst 卡片槽位，并持久化新顺序。"""
        if src_id == dst_id:
            return
        src_card = next((c for c in self.cards if c.mod.id == src_id), None)
        dst_card = next((c for c in self.cards if c.mod.id == dst_id), None)
        if src_card is None or dst_card is None:
            return
        si = self.grid_layout.indexOf(src_card)
        di = self.grid_layout.indexOf(dst_card)
        if si < 0 or di < 0:
            return
        sr, sc, _, _ = self.grid_layout.getItemPosition(si)
        dr, dc, _, _ = self.grid_layout.getItemPosition(di)
        self.grid_layout.removeWidget(src_card)
        self.grid_layout.removeWidget(dst_card)
        self.grid_layout.addWidget(src_card, dr, dc)
        self.grid_layout.addWidget(dst_card, sr, sc)
        i, j = self.cards.index(src_card), self.cards.index(dst_card)
        self.cards[i], self.cards[j] = self.cards[j], self.cards[i]
        self.context.config.set("modules.order", [c.mod.id for c in self.cards])

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
        # 模块页面窗口全局单例（与系统托盘共用），重复打开只会激活已有窗口
        from ui.module_pages import open_module_page
        if open_module_page(mod, parent=self.widget) is None:
            QtWidgets.QMessageBox.information(
                self.widget, mod.name, "该模块没有独立页面。"
            )
