"""todo_notes 标签管理对话框（todo 16）：两列宽矮布局。

左列 = 状态（新增/改名/删除/改色）+ 优先级（改色）；
右列 = 类别（新增/改名/删除/改色）。任何操作后立即重建对应列表，
数据经 modules.todo_store API 持久化（todo_statuses / todo_option_colors / todo_categories）。
CRUD 区块实现见 tag_manager_sections._SectionsMixin。
"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing
from ui.widgets import make_button, make_label
from ..todo_store import set_option_color
from .constants import (COLOR_COL_PRIORITY, PRIORITY_LABELS,
                        priority_color)
from .tag_manager_sections import _SectionsMixin


class _TagManagerDialog(_SectionsMixin):
    """标签管理：左列状态+优先级、右列类别；色块点击改色并持久化。

    用法::

        dlg = _TagManagerDialog(parent_widget)
        dlg.exec()  # 模态
    """

    def __init__(self, parent=None):
        self._dlg = QtWidgets.QDialog(parent)
        self._dlg.setWindowTitle("标签管理")
        self._dlg.setMinimumWidth(sizing()["tag_mgr_width"])
        root = QtWidgets.QVBoxLayout(self._dlg)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        self._status_rows = []
        self._priority_rows = []
        self._category_rows = []

        cols = QtWidgets.QGridLayout()
        cols.setSpacing(24)
        cols.setColumnStretch(0, 1)
        cols.setColumnStretch(1, 1)
        cols.addLayout(self._build_left(), 0, 0)
        cols.addLayout(self._build_right(), 0, 1)
        root.addLayout(cols)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = make_button("关闭", kind="primary")
        btn_close.clicked.connect(self._dlg.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)
        self._rebuild_statuses()
        self._rebuild_categories()

    # -- 两列骨架 -----------------------------------------------------

    def _build_left(self):
        lay = QtWidgets.QVBoxLayout()
        lay.setSpacing(8)
        lay.addWidget(make_label("状态", role="subtitle"))
        self._status_box = QtWidgets.QWidget(self._dlg)
        self._status_lay = QtWidgets.QVBoxLayout(self._status_box)
        self._status_lay.setContentsMargins(0, 0, 0, 0)
        self._status_lay.setSpacing(8)
        lay.addWidget(self._status_box)
        lay.addWidget(make_label("优先级", role="subtitle"))
        for val in (0, 1, 2, 3):
            sw = self._add_option_row(
                lay, PRIORITY_LABELS[val], priority_color(val),
                lambda sw, v=val: self._pick_color_for(
                    sw, lambda c, v2=v: set_option_color(
                        COLOR_COL_PRIORITY, str(v2), c)))
            self._priority_rows.append((sw, val))
        lay.addStretch(1)
        return lay

    def _build_right(self):
        lay = QtWidgets.QVBoxLayout()
        lay.setSpacing(8)
        lay.addWidget(make_label("类别", role="subtitle"))
        self._cat_box = QtWidgets.QWidget(self._dlg)
        self._cat_lay = QtWidgets.QVBoxLayout(self._cat_box)
        self._cat_lay.setContentsMargins(0, 0, 0, 0)
        self._cat_lay.setSpacing(8)
        lay.addWidget(self._cat_box)
        lay.addStretch(1)
        return lay

    # -- 优先级行（两个区块共用 _add_option_row / _pick_color_for） -----

    def _add_option_row(self, lay, name, color, on_click):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["dialog_spacing"])
        sw = self._make_swatch(color)
        sw.clicked.connect(lambda _=False: on_click(sw))
        row.addWidget(sw, 0, QtCore.Qt.AlignVCenter)
        row.addWidget(make_label(name), 0, QtCore.Qt.AlignVCenter)
        row.addStretch(1)
        lay.addLayout(row)
        return sw

    def exec(self):
        return self._dlg.exec()