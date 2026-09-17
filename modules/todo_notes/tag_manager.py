"""todo_notes 标签管理对话框（todo 16）：列出状态/优先级/类别选项与色块，点击色块改色。

类别区块支持新增/改名/删除/改色（todo 3）：任何操作后立即重建自身列表，
数据经 modules.todo_store 的类别 API 持久化（todo_categories 表）。
"""
from sqlite3 import IntegrityError

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing, theme_palette
from ui.widgets import make_button, make_label, make_line_edit
from ..todo_store import (add_category, delete_category, get_categories,
                          get_statuses, rename_category, set_option_color,
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

        # ── 类别（可新增/改名/删除/改色，操作后即时重建自身列表）──
        self._cat_box = QtWidgets.QWidget(self._dlg)
        self._cat_lay = QtWidgets.QVBoxLayout(self._cat_box)
        self._cat_lay.setContentsMargins(0, 0, 0, 0)
        self._cat_lay.setSpacing(8)
        lay.addWidget(self._cat_box)
        self._rebuild_categories()

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

    # -- 类别区块 -----------------------------------------------------

    def _rebuild_categories(self):
        """清空并重建类别区块（标题 + 行 + 新增输入行），反映当前 DB 状态。"""
        self._clear_layout(self._cat_lay)
        self._category_rows = []
        self._cat_lay.addWidget(make_label("类别", role="subtitle"))
        for c in get_categories():
            self._cat_lay.addLayout(self._make_category_row(c))
        if not self._category_rows:
            self._cat_lay.addWidget(make_label("（暂无类别）", role="body"))
        add_row = QtWidgets.QHBoxLayout()
        self._cat_input = make_line_edit("新类别名…", parent=self._dlg)
        self._cat_input.returnPressed.connect(self._on_add_category)
        add_row.addWidget(self._cat_input, 1)
        btn_add = make_button("新增类别", size="sm")
        btn_add.clicked.connect(lambda _=False: self._on_add_category())
        add_row.addWidget(btn_add)
        self._cat_lay.addLayout(add_row)

    def _clear_layout(self, layout):
        """递归清空布局：删除所有子控件与子布局（供重建）。"""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _make_category_row(self, name):
        """类别行：色块（改色）+ 名称 + 改名 + 删除。"""
        row = QtWidgets.QHBoxLayout()
        sw = self._make_swatch(category_color(name))
        sw.clicked.connect(
            lambda _=False, n=name: self._pick_color_for(
                sw, lambda c, n2=n: self._recolor_category(n2, c)))
        row.addWidget(sw)
        row.addWidget(make_label(name))
        btn_rename = make_button("改名", size="sm")
        btn_rename.clicked.connect(
            lambda _=False, n=name: self._on_rename_category(n))
        row.addWidget(btn_rename)
        btn_del = make_button("删除", size="sm", kind="danger")
        btn_del.clicked.connect(
            lambda _=False, n=name: self._on_delete_category(n))
        row.addWidget(btn_del)
        row.addStretch(1)
        self._category_rows.append((sw, name))
        return row

    def _on_add_category(self):
        """读取新增输入行 → add_category → 重建。空名/重名静默拒绝。"""
        text = self._cat_input.text().strip()
        if not text:
            return
        try:
            add_category(text)
        except (ValueError, IntegrityError):
            return
        self._rebuild_categories()

    def _on_rename_category(self, old):
        """改名按钮：弹输入框取新名 → rename_category → 重建。"""
        new, ok = QtWidgets.QInputDialog.getText(
            self._dlg, "重命名类别", "新名称：", text=old)
        if not ok:
            return
        self._apply_rename_category(old, new)

    def _apply_rename_category(self, old, new):
        """执行重命名并重建；空名/重名/未变化静默拒绝（DB 不变）。"""
        new = (new or "").strip()
        if not new or new == old:
            return
        try:
            rename_category(old, new)
        except (ValueError, IntegrityError):
            return
        self._rebuild_categories()

    def _on_delete_category(self, name):
        """删除类别并重建（引用行 category 置 ''，由 store 处理）。"""
        delete_category(name)
        self._rebuild_categories()

    def _recolor_category(self, name, color):
        """类别改色：写 todo_option_colors 后重建（新色块从 DB 取色）。"""
        set_option_color(COLOR_COL_CATEGORY, name, color)
        self._rebuild_categories()

    def exec(self):
        return self._dlg.exec()