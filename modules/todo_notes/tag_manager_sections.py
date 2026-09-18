"""tag_manager 的状态/类别 CRUD 区块（mixin）。

供 _TagManagerDialog 组合：状态区块（新增/改名/删除/改色）与类别区块
（新增/改名/删除/改色）共用 _clear_layout 重建机制。色块/选色工具也在此，
宿主（_TagManagerDialog）负责两列骨架与优先级行，依赖契约见类级注解：
self._dlg / self._status_lay / self._cat_lay，并维护 _status_rows / _category_rows。
"""
from sqlite3 import IntegrityError
from typing import Any

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing, theme_palette
from ui.widgets import make_button, make_label, make_line_edit
from ..todo_store import (add_category, add_status, delete_category,
                          delete_status, get_categories, get_statuses,
                          rename_category, rename_status, set_option_color,
                          set_status_color)
from .constants import (COLOR_COL_CATEGORY, category_color, status_color)


class _SectionsMixin:
    """状态 + 类别两个可重建区块的 CRUD 实现（宿主为 _TagManagerDialog）。"""

    _dlg: Any
    _status_lay: Any
    _cat_lay: Any

    # -- 色块 / 选色（两区块共用） --------------------------------------

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

    # -- 状态区块 -----------------------------------------------------

    def _rebuild_statuses(self):
        """清空并重建状态列表（行 + 新增输入行），反映当前 DB 状态。"""
        self._clear_layout(self._status_lay)
        self._status_rows = []
        for s in get_statuses():
            self._status_lay.addLayout(self._make_status_row(s))
        if not self._status_rows:
            self._status_lay.addWidget(make_label("（暂无状态）", role="body"))
        add_row = QtWidgets.QHBoxLayout()
        self._status_input = make_line_edit("新状态名…", parent=self._dlg)
        self._status_input.returnPressed.connect(self._on_add_status)
        add_row.addWidget(self._status_input, 1)
        btn_add = make_button("新增状态", size="sm")
        btn_add.clicked.connect(lambda _=False: self._on_add_status())
        add_row.addWidget(btn_add)
        self._status_lay.addLayout(add_row)

    def _make_status_row(self, s):
        """状态行：色块（改色）+ 名称 + 改名 + 删除。"""
        sid, name = s["id"], s["name"]
        row = QtWidgets.QHBoxLayout()
        sw = self._make_swatch(status_color(s))
        sw.clicked.connect(
            lambda _=False, sw2=sw, i=sid: self._pick_color_for(
                sw2, lambda c, i2=i: set_status_color(i2, c)))
        row.addWidget(sw)
        row.addWidget(make_label(name))
        btn_rename = make_button("改名", size="sm")
        btn_rename.clicked.connect(
            lambda _=False, i=sid, n=name: self._on_rename_status(i, n))
        row.addWidget(btn_rename)
        btn_del = make_button("删除", size="sm", kind="danger")
        btn_del.clicked.connect(
            lambda _=False, i=sid: self._on_delete_status(i))
        row.addWidget(btn_del)
        row.addStretch(1)
        self._status_rows.append((sw, sid))
        return row

    def _on_add_status(self):
        """读取新增输入行 → add_status → 重建。空名/重名静默拒绝。"""
        text = self._status_input.text().strip()
        if not text:
            return
        try:
            add_status(text)
        except (ValueError, IntegrityError):
            return
        self._rebuild_statuses()

    def _on_rename_status(self, sid, old):
        """改名按钮：弹输入框取新名 → rename_status → 重建。"""
        new, ok = QtWidgets.QInputDialog.getText(
            self._dlg, "重命名状态", "新名称：", text=old)
        if not ok:
            return
        self._apply_rename_status(sid, old, new)

    def _apply_rename_status(self, sid, old, new):
        """执行重命名并重建；空名/重名/未变化静默拒绝（DB 不变）。"""
        new = (new or "").strip()
        if not new or new == old:
            return
        try:
            rename_status(sid, new)
        except (ValueError, IntegrityError):
            return
        self._rebuild_statuses()

    def _on_delete_status(self, sid):
        """删除状态并重建（内置「待办」由 store 拒绝，静默）。"""
        try:
            delete_status(sid)
        except (ValueError, IntegrityError):
            return
        self._rebuild_statuses()

    # -- 类别区块 -----------------------------------------------------

    def _rebuild_categories(self):
        """清空并重建类别列表（行 + 新增输入行），反映当前 DB 状态。"""
        self._clear_layout(self._cat_lay)
        self._category_rows = []
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
        try:
            delete_category(name)
        except (ValueError, IntegrityError):
            return
        self._rebuild_categories()

    def _recolor_category(self, name, color):
        """类别改色：写 todo_option_colors 后重建（新色块从 DB 取色）。"""
        set_option_color(COLOR_COL_CATEGORY, name, color)
        self._rebuild_categories()