"""RSS 页面：三栏拖拽分割手柄。"""

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .page_layout import _RssPageWidget
from .text_utils import rss_palette
from core.theme.tokens import sizing


class _DragGrip(QtWidgets.QFrame):
    """三栏之间的可拖拽分割手柄。

    index=1：侧栏 | 列表；index=2：列表 | 预览。
    拖动时实时调整相邻两栏宽度，释放后保持新大小。
    """

    def __init__(self, page, index):
        super().__init__(page)
        self._page = page
        self._index = index
        self._dragging = False
        self._start_x = 0
        self._start_side = 0
        self._start_list = 0
        self._start_preview = 0
        self.setCursor(QtCore.Qt.SizeHorCursor)
        self.setMouseTracking(True)

    def _current_widths(self):
        return (self._page._side_col.width(),
                self._page._list_col.width(),
                self._page._preview_col.width())

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._dragging = True
            self._page._drag_active = True
            self._start_x = event.globalPosition().x()
            self._start_side, self._start_list, self._start_preview = self._current_widths()
            # 拖动时高亮分割线
            self.setStyleSheet("QFrame { background: %s; }" % rss_palette()["rss_accent"])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            dx = event.globalPosition().x() - self._start_x
            side, lst, prev = self._start_side, self._start_list, self._start_preview
            if self._index == 1:
                # 侧栏 | 列表：调整侧栏宽度
                new_side = max(120, min(side + dx, side + lst - 160))
                self._page._side_width = new_side
                self._page._list_width = lst - (new_side - side)
            else:
                # 列表 | 预览：调整预览宽度
                new_prev = max(160, min(prev - dx, prev + lst - 160))
                self._page._preview_width = new_prev
                self._page._list_width = lst + (prev - new_prev)
            self._page._apply_sizes()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._page._drag_active = False
            # 恢复默认样式（hover 由 QSS 处理）
            self.setStyleSheet("QFrame { background: transparent; }")
            # 拖拽结束：把三栏宽度比例存入配置，下次打开时恢复
            self._page._save_col_widths()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    def _make_grip(self, index):
        """创建可拖拽分割手柄（index=1 侧栏|列表，index=2 列表|预览）。

        拖动时实时调整相邻两栏宽度，释放后保持新大小；窗口整体缩放时
        按比例重置，避免三栏被挤压到零宽。
        """
        c = rss_palette()
        grip = _DragGrip(self, index)
        grip.setFixedWidth(7)
        # 置顶：预览列是后加入布局的不透明圆角面板，z 序高于手柄；
        # 一旦三栏宽度溢出/边缘重叠，手柄会被面板覆盖不可点。raise_ 保证
        # 拖拽区始终在最上层（配合 _clamp_widths 的宽度钳制双保险）。
        grip.raise_()
        grip.setStyleSheet(f"""
            QFrame {{
                background: transparent;
            }}
            QFrame:hover {{
                background: {c['rss_accent']};
            }}
        """)
        # 添加中间的竖线
        line = QtWidgets.QFrame(grip)
        line.setFixedSize(3, 36)
        line.setStyleSheet(f"background: {c['rss_border']}; border-radius: {sizing()['rss_radius_xs']}px;")
        grip._line = line
        layout = QtWidgets.QVBoxLayout(grip)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addStretch(1)
        layout.addWidget(line, 0, QtCore.Qt.AlignCenter)
        layout.addStretch(1)
        return grip