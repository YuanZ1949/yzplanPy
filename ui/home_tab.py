"""主页选项卡：QGraphicsView 画布，组件可拖拽移动、边框拉伸、
拖动切换顺序、点击添加弹出方块选择面板。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)

_, QtCore, QtGui, QtWidgets = import_qt()

_DEF_W = 340
_DEF_H = 240
_MIN_W = 180
_MIN_H = 120
_GAP = 8
_EDGE = 10
_STRETCH_THRESHOLD = 0.8
_DRAG_THRESHOLD = 6


class _FlowLayout:
    """变宽自适应流式布局：按各自宽度贪心换行，填充度较高的行自动拉伸填满容器。"""

    def __init__(self, gap=12, margin=10):
        self.gap = gap
        self.margin = margin

    def _row_height(self, row):
        return max((h for _, _, h in row), default=0)

    def compute(self, items, container_width):
        """
        items: [(cid, width, height)]  按 order 排列
        返回: {cid: (x, y, actual_w, actual_h)}, total_height
        """
        available = max(1, container_width - 2 * self.margin)

        rows = []
        cur = []
        cur_w = 0.0
        for cid, width, height in items:
            w = max(_MIN_W, int(width))
            if cur and cur_w + self.gap + w > available:
                rows.append(cur)
                cur = []
                cur_w = 0.0
            cur.append((cid, w, height))
            cur_w += w + (self.gap if cur_w else 0)

        if cur:
            rows.append(cur)

        positions = {}
        y = 0.0
        for row in rows:
            row_w = sum((w for _, w, _ in row)) + self.gap * (len(row) - 1)
            fill_rate = row_w / available if available else 0
            if fill_rate >= _STRETCH_THRESHOLD and row_w < available:
                extra = available - row_w
                x = self.margin
                for cid, w, h in row:
                    scale = w / row_w if row_w else 0
                    sw = w + extra * scale
                    positions[cid] = (int(x), int(y), int(sw), h)
                    x += sw + self.gap
            else:
                x = self.margin
                for cid, w, h in row:
                    positions[cid] = (int(x), int(y), w, h)
                    x += w + self.gap
            y += self._row_height(row) + self.gap

        total_h = y if y else 0
        return positions, int(total_h)


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

    def mouseMoveEvent(self, event):
        if event.button() == QtCore.Qt.NoButton:
            super().mouseMoveEvent(event)
            return
        if self._press_scene_pos is not None and not self._dragging:
            if (event.scenePos() - self._press_scene_pos).manhattanLength() >= _DRAG_THRESHOLD:
                self._dragging = True
                self._drag_start = event.scenePos() - self.pos()
                self.setZValue(100)
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
            self._owner._finish_swap(self)
            self._owner._relayout_all()
            event.accept()
            return
        self._drag_start = None
        super().mouseReleaseEvent(event)


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
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._active:
            return
        if self._mode in ("r", "c"):
            d = event.scenePos().x() - self._start.x()
            new_w = max(_MIN_W, int(self._orig_w + d))
            if new_w != self._card.width():
                self._card.setFixedWidth(new_w)
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
        self.update()
        event.accept()


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


class HomeTab:
    def __init__(self, context):
        self.context = context
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("home_tab")

        root = QtWidgets.QVBoxLayout(self.widget)
        root.setContentsMargins(0, 0, 0, 0)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(8, 6, 8, 4)
        self.btn_add = PrimaryPushButton("＋ 添加组件")
        self.btn_add.clicked.connect(self._show_add_popup)

        btn_menu = ToolButton(FluentIcon.SETTING)
        btn_menu.setFixedSize(36, 32)
        self._home_menu = QtWidgets.QMenu()
        self._home_menu.addAction("添加组件", self._show_add_popup)
        self._home_menu.addSeparator()
        self._home_menu.addAction("重置布局", self._reset_layout)
        self._home_menu.addAction("清空布局", self._clear_layout)
        btn_menu.clicked.connect(
            lambda: self._home_menu.popup(btn_menu.mapToGlobal(QtCore.QPoint(0, btn_menu.height())))
        )

        top.addWidget(self.btn_add)
        top.addStretch(1)
        top.addWidget(btn_menu)
        root.addLayout(top)

        self.scene = QtWidgets.QGraphicsScene(self.widget)
        self.view = _CanvasView(self.scene, self)
        self.view.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setStyleSheet("QGraphicsView { background: transparent; }")
        self.view.viewport().setAutoFillBackground(False)
        root.addWidget(self.view, 1)

        self._comp_index = self._available_components()
        self._proxies = {}
        self._handles = {}
        self._swap_line = None

        self._flow = _FlowLayout(
            gap=self.context.config.get("home.gap", 12),
            margin=self.context.config.get("home.margin", 10),
        )

        self._relayout_timer = QtCore.QTimer(self.widget)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(150)
        self._relayout_timer.timeout.connect(self._relayout_all)

        self._save_pending = QtCore.QTimer(self.widget)
        self._save_pending.setSingleShot(True)
        self._save_pending.timeout.connect(self._save_layout)

        self._load()
        self._render_all()

    def _available_components(self):
        comps = []
        for mod in self.context.registry.all():
            if not self.context.registry.is_enabled(mod.id):
                continue
            if not hasattr(mod, "create_home_widget"):
                continue
            comps.append((mod.id, mod.name))
        return comps

    def _load(self):
        id_map = dict(self._comp_index)
        layout = self.context.config.get("home.layout") or {}
        order = self.context.config.get("home.order")

        migrated = False
        new_layout = {}
        for cid, val in layout.items():
            if cid not in id_map:
                continue
            if isinstance(val, list) and len(val) == 4:
                new_layout[cid] = {"width": max(_MIN_W, int(val[2])),
                                   "height": max(_MIN_H, int(val[3]))}
                migrated = True
            elif isinstance(val, dict):
                entry = dict(val)
                if "col_span" in entry:
                    span = max(1, int(entry.pop("col_span")))
                    entry.setdefault("width", span * _DEF_W + (span - 1) * _GAP)
                    migrated = True
                if "width" in entry:
                    entry["width"] = max(_MIN_W, int(entry["width"]))
                if "height" in entry:
                    entry["height"] = max(_MIN_H, int(entry["height"]))
                new_layout[cid] = entry
        if migrated:
            self.context.config.set("home.layout", new_layout)
        layout = new_layout

        if isinstance(order, list) and order:
            self._order = [cid for cid in order if cid in id_map]
        else:
            self._order = [cid for cid in layout if cid in id_map]

        self._saved = {cid: dict(v) for cid, v in layout.items() if cid in id_map}

        for cid in self._order:
            if cid not in self._saved:
                self._saved[cid] = {"width": _DEF_W, "height": _DEF_H}

        self._save_order()

    def _render_all(self):
        for cid, proxy in list(self._proxies.items()):
            self.scene.removeItem(proxy)
        self._proxies.clear()
        self._handles.clear()

        for cid in self._order:
            self._create_card(cid)

        self._relayout_all()
        self._save_order()

    def _create_card(self, cid):
        """创建组件卡片并加入场景，但不设置位置（由 _relayout_all 统一设）。"""
        mod = self.context.registry.get(cid)
        if mod is None:
            return

        saved = self._saved.get(cid, {})
        card_w = saved.get("width", _DEF_W)

        card = CardWidget()
        card.setObjectName(f"home_card_{cid}")
        card.setMinimumWidth(_MIN_W)
        card.setFixedWidth(card_w)

        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(10, 4, 10, 6)
        head = QtWidgets.QHBoxLayout()
        title = StrongBodyLabel(mod.name)

        close = TransparentToolButton("\u2715")
        close.setToolTip("移除")
        close.clicked.connect(lambda c=cid: self._remove_component(c))
        close.setVisible(False)

        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        lay.addLayout(head)

        card._action_btns = [close]

        def _enter(_event):
            for b in card._action_btns:
                b.setVisible(True)

        def _leave(_event):
            for b in card._action_btns:
                b.setVisible(False)

        card.enterEvent = _enter
        card.leaveEvent = _leave

        inner = mod.create_home_widget(card)
        if inner is not None:
            lay.addWidget(inner, 1)
            if hasattr(inner, "render"):
                try:
                    inner.render()
                except Exception:
                    pass

        proxy = _Proxy(self)
        proxy.setWidget(card)
        self.scene.addItem(proxy)
        self._proxies[cid] = proxy

        handles = {}
        for mode in ("r", "b", "c"):
            handle = _Handle(self, proxy, card, mode, cid)
            handle.setParentItem(proxy)
            handles[mode] = handle
        self._handles[cid] = handles
        self._update_handles(proxy, card)

    def _update_handles(self, proxy, card):
        cid = next((c for c, p in self._proxies.items() if p is proxy), None)
        if cid is None or cid not in self._handles:
            return
        w, h = card.width(), card.height()
        hs = self._handles[cid]
        hs["r"].setPos(w, h // 2)
        hs["b"].setPos(w // 2, h)
        hs["c"].setPos(w, h)

    def _relayout_all(self):
        """重新计算流式布局（窗口 resize 或尺寸变更时调用）。"""
        vw = max(400, self.view.viewport().width() - 20)

        items = []
        for cid in self._order:
            saved = self._saved.get(cid, {})
            w = saved.get("width", _DEF_W)
            proxy = self._proxies.get(cid)
            h = saved.get("height", proxy.size().height() if proxy else _DEF_H)
            h = max(_MIN_H, int(h))
            items.append((cid, w, h))

        positions, total_h = self._flow.compute(items, vw)

        for cid, (x, y, w, h) in positions.items():
            if cid in self._proxies:
                proxy = self._proxies[cid]
                proxy.widget().setFixedSize(w, h)
                self._update_handles(proxy, proxy.widget())
                end_pos = QtCore.QPointF(x, y)
                if proxy.pos() != end_pos:
                    anim = QtCore.QPropertyAnimation(proxy, b"pos")
                    anim.setDuration(250)
                    anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
                    anim.setStartValue(proxy.pos())
                    anim.setEndValue(end_pos)
                    anim.start()
                    if not hasattr(self, "_animations"):
                        self._animations = []
                    self._animations.append(anim)
                else:
                    proxy.setPos(x, y)

        self.view._sync_scene()

    def _rebuild_component(self, cid, new_w, new_h):
        old_proxy = self._proxies.get(cid)
        if old_proxy is None:
            return
        self.scene.removeItem(old_proxy)
        del self._proxies[cid]
        self._handles.pop(cid, None)
        saved = self._saved.get(cid, {})
        saved["width"] = max(_MIN_W, int(new_w))
        saved["height"] = max(_MIN_H, int(new_h))
        self._create_card(cid)
        self._relayout_all()

    def _highlight_swap(self, dragging_proxy):
        drag_cid = next((c for c, p in self._proxies.items() if p is dragging_proxy), None)
        if drag_cid is None:
            return
        target_cid = self._find_swap_target(dragging_proxy, drag_cid)
        if self._swap_line is None and target_cid:
            self._swap_line = self.scene.addRect(
                0, 0, 0, 0,
                QtGui.QPen(QtGui.QColor(0, 120, 215, 180), 2, QtCore.Qt.DashLine),
                QtGui.QBrush(QtCore.Qt.NoBrush),
            )
            self._swap_line.setZValue(50)
        if target_cid and target_cid in self._proxies:
            tp = self._proxies[target_cid]
            r = tp.widget().rect()
            self._swap_line.setRect(tp.pos().x(), tp.pos().y(), r.width(), r.height())
            self._swap_line.setVisible(True)
        elif self._swap_line:
            self._swap_line.setVisible(False)

    def _find_swap_target(self, dragging_proxy, drag_cid):
        center = dragging_proxy.pos() + QtCore.QPointF(
            dragging_proxy.widget().width() / 2,
            dragging_proxy.widget().height() / 2,
        )
        best_cid = None
        best_dist = float("inf")
        for cid, proxy in self._proxies.items():
            if cid == drag_cid:
                continue
            r = proxy.widget().rect()
            pc = proxy.pos() + QtCore.QPointF(r.width() / 2, r.height() / 2)
            dist = (center - pc).manhattanLength()
            if dist < best_dist and dist < max(r.width(), r.height()):
                best_dist = dist
                best_cid = cid
        return best_cid

    def _finish_swap(self, dragging_proxy):
        if self._swap_line:
            self._swap_line.setVisible(False)
            self.scene.removeItem(self._swap_line)
            self._swap_line = None
        drag_cid = next((c for c, p in self._proxies.items() if p is dragging_proxy), None)
        if drag_cid is None:
            return
        target_cid = self._find_swap_target(dragging_proxy, drag_cid)
        if target_cid and target_cid in self._proxies:
            di = self._order.index(drag_cid)
            ti = self._order.index(target_cid)
            self._order[di], self._order[ti] = self._order[ti], self._order[di]
            self._schedule_save()
            self._save_order()

    def _show_add_popup(self):
        popup = _AddPopup(self, self.widget)
        btn_pos = self.btn_add.mapToGlobal(QtCore.QPoint(0, self.btn_add.height()))
        popup.move(btn_pos)
        popup.show()

    def _add_component(self, cid):
        if cid not in self._order:
            self._order.append(cid)
            self._render_all()

    def _remove_component(self, cid):
        if cid in self._order:
            self._order.remove(cid)
        if cid in self._saved:
            del self._saved[cid]
        self._render_all()

    def _reset_layout(self):
        self._order = [cid for cid, _ in self._comp_index]
        self._saved = {cid: {"width": _DEF_W, "height": _DEF_H} for cid in self._order}
        self._render_all()

    def _clear_layout(self):
        self._order = []
        self._saved = {}
        self._render_all()

    def _schedule_save(self):
        self._save_pending.start(300)

    def _save_layout(self):
        layout = {}
        for cid in self._order:
            saved = self._saved.get(cid, {})
            layout[cid] = {
                "width": saved.get("width", _DEF_W),
                "height": saved.get("height", _DEF_H),
            }
        self.context.config.set("home.layout", layout)

    def _save_order(self):
        self.context.config.set("home.order", self._order)
