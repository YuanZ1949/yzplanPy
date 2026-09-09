"""home_tab.tab_core: HomeTab 核心（__init__/_available_components/_load）。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon, PrimaryPushButton, ToolButton
from .canvas import _CanvasView
from .constants import _DEF_H, _DEF_W, _GAP, _MIN_H, _MIN_W
from .flow import _FlowLayout
_, QtCore, QtGui, QtWidgets = import_qt()

class HomeTab:
    def __init__(self, context):
        self.context = context
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("home_tab")

        self._animations = {}   # cid -> QPropertyAnimation，避免同一 proxy 上叠加动画
        self._dragging_cid = None

        root = QtWidgets.QVBoxLayout(self.widget)
        root.setContentsMargins(0, 0, 0, 0)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(8, 6, 8, 4)
        self.btn_add = PrimaryPushButton("＋ 添加组件")
        self.btn_add.clicked.connect(self._show_add_popup)  # type: ignore[reportAttributeAccessIssue]

        btn_menu = ToolButton(FluentIcon.SETTING)
        btn_menu.setFixedSize(36, 32)
        self._home_menu = QtWidgets.QMenu()
        self._home_menu.addAction("添加组件", self._show_add_popup)  # type: ignore[reportAttributeAccessIssue]
        self._home_menu.addSeparator()
        self._home_menu.addAction("重置布局", self._reset_layout)  # type: ignore[reportAttributeAccessIssue]
        self._home_menu.addAction("清空布局", self._clear_layout)  # type: ignore[reportAttributeAccessIssue]
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
        self._relayout_timer.timeout.connect(self._relayout_all)  # type: ignore[reportAttributeAccessIssue]

        self._save_pending = QtCore.QTimer(self.widget)
        self._save_pending.setSingleShot(True)
        self._save_pending.timeout.connect(self._save_layout)  # type: ignore[reportAttributeAccessIssue]

        self._load()
        self._render_all()  # type: ignore[reportAttributeAccessIssue]

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

        self._save_order()  # type: ignore[reportAttributeAccessIssue]
