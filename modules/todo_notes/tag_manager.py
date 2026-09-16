"""todo_notes 标签管理对话框（todo 16）：列出状态/优先级/类别选项与色块，点击色块改色。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing, theme_palette
from ui.widgets import make_button, make_label
from ..todo_store import (get_categories, get_statuses, set_option_color,
                          set_status_color)
from .constants import (COLOR_COL_CATEGORY, COLOR_COL_PRIORITY,
                        PRIORITY_LABELS, category_color, priority_color,
                        status_color)


class _TagManagerDialog:
    """集中改色对话框：所有列的所有选项 + 色块，点击色块改色并持久化。

    用法::

        dlg = _TagManagerDialog(parent_widget)
        dlg.exec()  # 模态
    """

    def __init__(self, parent=None):
        self._dlg = QtWidgets.QDialog(parent)
        self._dlg.setWindowTitle("标签管理")
        self._dlg.setMinimumWidth(360)
        lay = QtWidgets.QVBoxLayout(self._dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        self._status_rows = []
        self._priority_rows = []
        self._category_rows = []

        # ── 状态 ──
        lay.addWidget(make_label("状态", role="subtitle"))
        for s in get_statuses():
            sw = self._add_option_row(
                lay, s["name"], status_color(s),
                lambda sw, sid=s["id"]: self._pick_color_for(
                    sw, lambda c: set_status_color(sid, c)))
            self._status_rows.append((sw, s["id"]))

        # ── 优先级 ──
        lay.addWidget(make_label("优先级", role="subtitle"))
        for val in (0, 1, 2, 3):
            sw = self._add_option_row(
                lay, PRIORITY_LABELS[val], priority_color(val),
                lambda sw, v=val: self._pick_color_for(
                    sw, lambda c, v2=v: set_option_color(
                        COLOR_COL_PRIORITY, str(v2), c)))
            self._priority_rows.append((sw, val))

        # ── 类别 ──
        lay.addWidget(make_label("类别", role="subtitle"))
        for c in get_categories():
            sw = self._add_option_row(
                lay, c, category_color(c),
                lambda sw, name=c: self._pick_color_for(
                    sw, lambda c2, n=name: set_option_color(
                        COLOR_COL_CATEGORY, n, c2)))
            self._category_rows.append((sw, c))

        if not self._category_rows:
            lay.addWidget(make_label("（暂无类别）", role="body"))

        # ── 关闭按钮 ──
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = make_button("关闭", kind="primary")
        btn_close.clicked.connect(self._dlg.accept)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    # -- 内部 --------------------------------------------------------

    def _add_option_row(self, lay, name, color, on_click):
        row = QtWidgets.QHBoxLayout()
        sw = self._make_swatch(color)
        sw.clicked.connect(lambda _=False: on_click(sw))
        row.addWidget(sw)
        row.addWidget(make_label(name))
        row.addStretch(1)
        lay.addLayout(row)
        return sw

    def _make_swatch(self, color):
        p = theme_palette()
        sz = sizing()
        btn = make_button("", size="sm")
        btn.setFixedWidth(btn.height())
        btn.setStyleSheet(
            f"QPushButton {{ background: {color};"
            f" border: 1px solid {p['border']};"
            f" border-radius: {sz['radius_sm']}px; }}"
        )
        btn._swatch_color = color  # type: ignore[attr-defined]
        return btn

    def _set_swatch_color_of(self, sw, color):
        p = theme_palette()
        sz = sizing()
        sw.setStyleSheet(
            f"QPushButton {{ background: {color};"
            f" border: 1px solid {p['border']};"
            f" border-radius: {sz['radius_sm']}px; }}"
        )
        sw._swatch_color = color  # type: ignore[attr-defined]

    def _pick_color_for(self, sw, persist):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(sw._swatch_color), self._dlg, "设置颜色")  # type: ignore[attr-defined]
        if not color.isValid():
            return
        hex_color = color.name()
        persist(hex_color)
        self._set_swatch_color_of(sw, hex_color)

    def exec(self):
        return self._dlg.exec()