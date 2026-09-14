"""webview_control - 隐藏宿主恢复对话框。"""
import os
from collections.abc import Callable
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from ui.widgets import make_button, make_label

_, QtCore, QtGui, QtWidgets = import_qt()


def _visible_hosts(hosts, hidden):
    """过滤隐藏宿主：exe 不在 hidden 集合中的保留原序。"""
    hset = set(hidden)
    return [h for h in hosts if h["exe"] not in hset]


class _HiddenList(QtWidgets.QListWidget):
    """Delete 键删除选中项 = 解除隐藏。"""

    _on_delete_pressed: Callable[[], None] | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on_delete_pressed = None

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Delete and self._on_delete_pressed is not None:
            self._on_delete_pressed()
            e.accept()
            return
        super().keyPressEvent(e)


def show_hidden_dialog(parent, hidden, on_unhide):
    """弹出「显示所有隐藏项」对话框。

    on_unhide(exe): 由调用方负责从 hidden 移除 + save + refresh。
    返回对话框实例（非模态），供测试直接驱动。
    """
    _p = theme_palette()
    _sz = sizing()

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("显示所有隐藏项")
    dlg.resize(420, 320)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    tip = make_label("Delete 键删除选中项 = 解除隐藏", role="caption", parent=dlg)
    lay.addWidget(tip)

    lst = _HiddenList(dlg)
    for exe in hidden:
        item = QtWidgets.QListWidgetItem(os.path.basename(exe) or exe)
        item.setToolTip(exe)
        item.setData(QtCore.Qt.UserRole, exe)
        lst.addItem(item)
    lst.setStyleSheet(
        f"QListWidget {{ background: {_p['bg_control']}; color: {_p['text_primary']};"
        f" border: 1px solid {_p['border']}; border-radius: {_sz['radius_md']}px; }}"
        f"QListWidget::item:selected {{ background: {_p['table_sel_strong_bg']}; }}")
    lay.addWidget(lst, 1)

    btn_row = QtWidgets.QHBoxLayout()
    btn_row.addStretch(1)
    btn_restore_all = make_button("全部恢复", kind="primary", size="md", parent=dlg)
    btn_close = make_button("关闭", kind="default", size="md", parent=dlg)
    btn_row.addWidget(btn_restore_all)
    btn_row.addWidget(btn_close)
    lay.addLayout(btn_row)

    def _on_delete_pressed():
        row = lst.currentRow()
        if row < 0:
            return
        item = lst.takeItem(row)
        on_unhide(item.data(QtCore.Qt.UserRole))

    def _on_restore_all():
        while lst.count():
            item = lst.takeItem(0)
            on_unhide(item.data(QtCore.Qt.UserRole))
        dlg.accept()

    lst._on_delete_pressed = _on_delete_pressed
    btn_restore_all.clicked.connect(_on_restore_all)
    btn_close.clicked.connect(dlg.reject)

    dlg._on_delete_pressed = _on_delete_pressed
    dlg._list = lst
    dlg.show()
    return dlg