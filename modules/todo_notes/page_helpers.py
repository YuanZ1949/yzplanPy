"""todo_notes 页面辅助：_page_context_menu/_maybe_reset_done_on_content_change/_TodoEditDialog。

[_build_todo_menu / _pick_cell_color_for: todo 16 右键改色]
"""
from datetime import datetime
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from ..todo_store import (delete_todo, get_categories, get_or_create_status,
                          get_statuses, get_option_color, set_option_color,
                          set_status_color, update_todo)
from .constants import (COL_CATEGORY, COL_PRIORITY, COL_STATUS,
                        COLOR_COL_CATEGORY, COLOR_COL_PRIORITY,
                        category_color, priority_color, status_color)
from .date_theme import _apply_date_theme


def _build_todo_menu(todo, col, color_row):
    """构建便签右键菜单；选项列（状态/优先级/类别）附带「设置颜色」入口。

    Returns:
        (menu, actions_dict): actions_dict keys —
            toggle/copy/edit/high/hi/mid/low/del/color
    """
    menu = QtWidgets.QMenu()
    act_toggle = menu.addAction("标记已完成" if not todo["done"] else "标记未完成")
    menu.addSeparator()
    act_copy = menu.addAction("复制")
    act_edit = menu.addAction("编辑")
    menu.addSeparator()
    act_high = menu.addAction("优先级: 紧急")
    act_hi = menu.addAction("优先级: 高")
    act_mid = menu.addAction("优先级: 中")
    act_low = menu.addAction("优先级: 低")
    menu.addSeparator()
    act_del = menu.addAction("删除")
    act_color = None
    if col in (COL_STATUS, COL_PRIORITY, COL_CATEGORY) and color_row >= 0:
        menu.addSeparator()
        act_color = menu.addAction("设置颜色...")
    return menu, {
        "toggle": act_toggle, "copy": act_copy, "edit": act_edit,
        "high": act_high, "hi": act_hi, "mid": act_mid, "low": act_low,
        "del": act_del, "color": act_color,
    }


def _pick_cell_color_for(table, row, col, refresh):
    """选项单元格右键改色：QColorDialog 选色 → 持久化 → 刷新。"""
    item = table.item(row, col)
    if item is None:
        return
    if col == COL_STATUS:
        sid = item.data(QtCore.Qt.UserRole)
        st = next((s for s in get_statuses() if s["id"] == sid), None)
        current = status_color(st)
    elif col == COL_PRIORITY:
        val = item.data(QtCore.Qt.UserRole)
        current = priority_color(val)
    else:
        cat = item.text()
        if not cat:
            return
        current = category_color(cat)
    color = QtWidgets.QColorDialog.getColor(
        QtGui.QColor(current), table.window(), "设置颜色")
    if not color.isValid():
        return
    hex_color = color.name()
    if col == COL_STATUS:
        set_status_color(sid, hex_color)
    elif col == COL_PRIORITY:
        set_option_color(COLOR_COL_PRIORITY, str(val), hex_color)
    else:
        set_option_color(COLOR_COL_CATEGORY, cat, hex_color)
    refresh()


def _page_context_menu(pos, table, all_todos, refresh, on_copy=None):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()

    rows = set(idx.row() for idx in table.selectedIndexes())
    if not rows:
        return
    row = min(rows)
    if row >= len(all_todos):
        return
    todo = all_todos[row]
    col_at = table.columnAt(pos.x())
    row_at = table.rowAt(pos.y())

    menu, acts = _build_todo_menu(todo, col_at, row_at)
    action = menu.exec_(table.mapToGlobal(pos))
    if not action:
        return
    if action == acts["toggle"]:
        update_todo(todo["id"], done=0 if todo["done"] else 1)
        refresh()
    elif action == acts["copy"]:
        if len(rows) > 1:
            items = []
            for r in sorted(rows):
                if r < len(all_todos):
                    t = all_todos[r]
                    items.append(t["title"] + (" - " + t["content"] if t["content"] else ""))
                QtWidgets.QApplication.clipboard().setText("\n".join(items))
        else:
            text = todo["title"]
            if todo["content"]:
                text += " - " + todo["content"]
            QtWidgets.QApplication.clipboard().setText(text)
        if on_copy:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success("已复制", "已复制到剪贴板", parent=table.window(),
                            position=InfoBarPosition.TOP_RIGHT, duration=2000)
    elif action == acts["high"]:
        update_todo(todo["id"], priority=3)
        refresh()
    elif action == acts["hi"]:
        update_todo(todo["id"], priority=2)
        refresh()
    elif action == acts["mid"]:
        update_todo(todo["id"], priority=1)
        refresh()
    elif action == acts["low"]:
        update_todo(todo["id"], priority=0)
        refresh()
    elif action == acts["del"]:
        delete_todo(todo["id"])
        refresh()
    elif action == acts["color"]:
        _pick_cell_color_for(table, row_at, col_at, refresh)


def _maybe_reset_done_on_content_change(todo_id, old_content, new_content):
    """内容字段被修改说明可能有新增事项，自动将该条目状态重置为「待办」。

    done 与 status_id 同步归零：todo 2 后状态列渲染由 status_id 驱动，
    仅置 done=0 会让状态列仍显示旧状态（用户报告"没看到生效"）。
    """
    if old_content != new_content:
        update_todo(todo_id, done=0, status_id=get_or_create_status("待办"))


class _TodoEditDialog:
    def __init__(self, parent=None, todo=None):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        from qfluentwidgets import ComboBox, EditableComboBox

        self._dlg = QtWidgets.QDialog(parent)
        self._dlg.setWindowTitle("编辑待办" if todo else "新增待办")
        self._dlg.setMinimumSize(400, 320)

        lay = QtWidgets.QVBoxLayout(self._dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        lay.addWidget(QtWidgets.QLabel("标题:"))
        self.title_input = QtWidgets.QLineEdit()
        self.title_input.setText(todo["title"] if todo else "")
        lay.addWidget(self.title_input)

        lay.addWidget(QtWidgets.QLabel("内容:"))
        self.content_input = QtWidgets.QPlainTextEdit()
        self.content_input.setMaximumHeight(100)
        self.content_input.setPlainText(todo["content"] if todo else "")
        lay.addWidget(self.content_input)

        pri_row = QtWidgets.QHBoxLayout()
        pri_row.addWidget(QtWidgets.QLabel("优先级:"))
        self.pri_combo = ComboBox()
        self.pri_combo.addItem("低", userData=0)
        self.pri_combo.addItem("中", userData=1)
        self.pri_combo.addItem("高", userData=2)
        self.pri_combo.addItem("紧急", userData=3)
        if todo:
            for i in range(self.pri_combo.count()):
                if self.pri_combo.itemData(i) == todo["priority"]:
                    self.pri_combo.setCurrentIndex(i)
                    break
        pri_row.addWidget(self.pri_combo)
        pri_row.addStretch(1)
        lay.addLayout(pri_row)

        cat_row = QtWidgets.QHBoxLayout()
        cat_row.addWidget(QtWidgets.QLabel("类别:"))
        self.cat_combo = EditableComboBox()
        self.cat_combo.addItem("（无类别）", userData="")
        for c in get_categories():
            self.cat_combo.addItem(c, userData=c)
        self.cat_combo.setPlaceholderText("选择或输入新类别")
        if todo and todo.get("category"):
            idx = self.cat_combo.findData(todo["category"])
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)
            else:
                self.cat_combo.setCurrentText(todo["category"])
        cat_row.addWidget(self.cat_combo)
        cat_row.addStretch(1)
        lay.addLayout(cat_row)

        due_row = QtWidgets.QHBoxLayout()
        due_row.addWidget(QtWidgets.QLabel("截止日期:"))
        self.due_check = QtWidgets.QCheckBox("启用")
        due_row.addWidget(self.due_check)
        self.due_date = QtWidgets.QDateEdit()
        self.due_date.setCalendarPopup(True)
        _apply_date_theme(self.due_date)
        self.due_date.setDate(QtCore.QDate.currentDate())
        self.due_date.setEnabled(False)
        due_row.addWidget(self.due_date)
        due_row.addStretch(1)
        lay.addLayout(due_row)

        if todo and todo["due_date"]:
            self.due_check.setChecked(True)
            self.due_date.setEnabled(True)
            try:
                d = datetime.strptime(todo["due_date"], "%Y-%m-%d")
                self.due_date.setDate(QtCore.QDate(d.year, d.month, d.day))
            except ValueError:
                pass

        self.due_check.toggled.connect(self.due_date.setEnabled)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self._dlg.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.clicked.connect(self._dlg.accept)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def exec(self):
        return self._dlg.exec()

    def get_data(self):
        due = None
        if self.due_check.isChecked():
            d = self.due_date.date()
            due = f"{d.year()}-{d.month():02d}-{d.day():02d}"
        return {
            "title": self.title_input.text().strip(),
            "content": self.content_input.toPlainText().strip(),
            "priority": self.pri_combo.currentData(),
            "category": (self.cat_combo.currentText() or "").strip(),
            "due_date": due,
        }
