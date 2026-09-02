"""todo_notes 模块：便签/待办事项管理，支持优先级、类别、截止日期、搜索筛选、内联编辑与复制。"""
import shutil
import sqlite3
from datetime import datetime, timedelta

from .base import ModuleBase

from core.constants import DB_PATH
from core.perf import trace
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS todo_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            priority INTEGER DEFAULT 1,
            category TEXT DEFAULT '',
            done INTEGER DEFAULT 0,
            due_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(todo_notes)").fetchall()]
    if "category" not in cols:
        conn.execute("ALTER TABLE todo_notes ADD COLUMN category TEXT DEFAULT ''")
    conn.commit()
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_todo(title, content="", priority=1, due_date=None, category=""):
    conn = _get_conn()
    now = _now()
    cur = conn.execute(
        "INSERT INTO todo_notes (title, content, priority, category, done, due_date, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
        (title, content, priority, category, due_date, now, now),
    )
    conn.commit()
    todo_id = cur.lastrowid
    conn.close()
    return todo_id


def update_todo(todo_id, **kwargs):
    conn = _get_conn()
    fields = []
    values = []
    for key in ("title", "content", "priority", "category", "done", "due_date"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
    if not fields:
        conn.close()
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(todo_id)
    conn.execute(f"UPDATE todo_notes SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_todo(todo_id):
    conn = _get_conn()
    conn.execute("DELETE FROM todo_notes WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()


@trace()
def get_todos(done=None, keyword=None, order="created_at", category=None):
    conn = _get_conn()
    query = "SELECT id, title, content, priority, category, done, due_date, created_at, updated_at FROM todo_notes"
    conditions = []
    params = []
    if done is not None:
        conditions.append("done = ?")
        params.append(done)
    if keyword:
        conditions.append("(title LIKE ? OR content LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])
    if category:
        conditions.append("category = ?")
        params.append(category)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    order_map = {
        "created_at": "created_at DESC",
        "priority": "priority DESC, created_at DESC",
        "due_date": "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC",
    }
    query += f" ORDER BY {order_map.get(order, 'created_at DESC')}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "content": r[2], "priority": r[3],
         "category": r[4] or "", "done": r[5], "due_date": r[6],
         "created_at": r[7], "updated_at": r[8]}
        for r in rows
    ]


def get_categories():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT category FROM todo_notes WHERE category != '' ORDER BY category"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_todo_count():
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) FROM todo_notes WHERE done = 0").fetchone()
    conn.close()
    return row[0] if row else 0


PRIORITY_LABELS = {0: "低", 1: "中", 2: "高", 3: "紧急"}
PRIORITY_COLORS = {0: "#888", 1: "#e67e22", 2: "#e74c3c", 3: "#c0392b"}


MODULE_INFO = {
    "id": "todo_notes",
    "name": "便签待办",
    "description": "待办事项管理，支持优先级和截止日期",
}


class Module(ModuleBase):
    MODULE_ID = "todo_notes"
    MODULE_NAME = "便签待办"
    MODULE_DESCRIPTION = "待办事项管理，支持优先级和截止日期"
    ENABLED_BY_DEFAULT = True

    def start(self):
        super().start()
        _get_conn()

    def stop(self):
        super().stop()

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)

    def create_page(self, parent):
        return _make_page_widget(self, parent)


# ── 主页卡片 ──────────────────────────────────────────────────────────

def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 6)
    lay.setSpacing(4)

    header = QtWidgets.QHBoxLayout()
    title = StrongBodyLabel("待办事项")
    header.addWidget(title)
    header.addStretch(1)
    count_lbl = BodyLabel("")
    count_lbl.setStyleSheet("color: #888;")
    header.addWidget(count_lbl)
    lay.addLayout(header)

    list_widget = QtWidgets.QListWidget()
    list_widget.setStyleSheet(
        "QListWidget { border: none; background: transparent; }"
        "QListWidget::item { padding: 5px 4px; border-bottom: 1px solid rgba(128,128,128,0.15); border-radius: 4px; }"
        "QListWidget::item:hover { background: transparent; }"
        "QListWidget::item:selected { background: rgba(128,128,128,0.12); }"
        "QListWidget::item:selected:hover { background: rgba(128,128,128,0.12); }"
    )
    lay.addWidget(list_widget, 1)

    add_row = QtWidgets.QHBoxLayout()
    add_input = QtWidgets.QLineEdit()
    add_input.setPlaceholderText("输入待办事项...")
    add_btn = PrimaryPushButton("添加")
    add_row.addWidget(add_input, 1)
    add_row.addWidget(add_btn)
    lay.addLayout(add_row)

    def refresh():
        list_widget.clear()
        todos = get_todos(done=0, order="due_date")
        overdue = get_todos(done=0, order="due_date")
        now = datetime.now().date()
        pending = [t for t in todos if not t["done"]]
        done_items = get_todos(done=1, order="created_at")[:5]
        count_lbl.setText(f"{len(pending)} 项待办")

        for t in pending:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, t["id"])
            text = t["title"]
            if t["due_date"]:
                try:
                    due = datetime.strptime(t["due_date"], "%Y-%m-%d").date()
                    days = (due - now).days
                    if days < 0:
                        text += f"  [逾期{-days}天]"
                    elif days == 0:
                        text += "  [今天截止]"
                    elif days == 1:
                        text += "  [明天截止]"
                    else:
                        text += f"  [{days}天后]"
                except ValueError:
                    pass
            item.setText(f"● {text}")
            color = PRIORITY_COLORS.get(t["priority"], "#888")
            item.setForeground(QtGui.QColor(color))
            list_widget.addItem(item)

        for t in done_items:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, t["id"])
            item.setText(f"✓ {t['title']}")
            item.setForeground(QtGui.QColor("#aaa"))
            f = item.font()
            f.setStrikeOut(True)
            item.setFont(f)
            list_widget.addItem(item)

    def add_todo_from_input():
        text = add_input.text().strip()
        if not text:
            return
        add_todo(text)
        add_input.clear()
        refresh()

    add_btn.clicked.connect(add_todo_from_input)
    add_input.returnPressed.connect(add_todo_from_input)

    list_widget.itemDoubleClicked.connect(lambda item: _toggle_done(item, refresh))
    list_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    list_widget.customContextMenuRequested.connect(lambda pos: _home_context_menu(pos, list_widget, refresh))

    refresh()
    owner._home_refresh = refresh
    return w


def _toggle_done(item, refresh):
    todo_id = item.data(QtCore.Qt.UserRole)
    if todo_id is None:
        return
    todos = get_todos()
    for t in todos:
        if t["id"] == todo_id:
            update_todo(todo_id, done=0 if t["done"] else 1)
            break
    refresh()


def _home_context_menu(pos, list_widget, refresh):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()

    item = list_widget.itemAt(pos)
    if not item:
        return
    todo_id = item.data(QtCore.Qt.UserRole)
    if todo_id is None:
        return

    menu = QtWidgets.QMenu()
    act_toggle = menu.addAction("切换完成状态")
    menu.addSeparator()
    act_high = menu.addAction("优先级: 紧急")
    act_hi = menu.addAction("优先级: 高")
    act_mid = menu.addAction("优先级: 中")
    act_low = menu.addAction("优先级: 低")
    menu.addSeparator()
    act_del = menu.addAction("删除")

    action = menu.exec_(list_widget.mapToGlobal(pos))
    if not action:
        return
    if action == act_toggle:
        _toggle_done(item, refresh)
    elif action == act_high:
        update_todo(todo_id, priority=3)
        refresh()
    elif action == act_hi:
        update_todo(todo_id, priority=2)
        refresh()
    elif action == act_mid:
        update_todo(todo_id, priority=1)
        refresh()
    elif action == act_low:
        update_todo(todo_id, priority=0)
        refresh()
    elif action == act_del:
        delete_todo(todo_id)
        refresh()


def _apply_date_theme(date_edit):
    """让 QDateEdit 弹出的日历与主程序主题一致（避免黑底黑字混在一起）。"""
    from core.theme import resolve_dark
    dark = resolve_dark("auto")
    qss = None
    if dark:
        qss = (
            "QCalendarWidget QWidget#qt_calendar_navigationbar { background: #232323; }"
            "QCalendarWidget QToolButton { color: #e6e6e6; background: transparent; }"
            "QCalendarWidget QAbstractItemView { background: #1e1e1e; color: #e6e6e6;"
            " selection-background-color: #3a6ea5; selection-color: #ffffff; }"
            "QCalendarWidget QSpinBox { background: #2b2b2b; color: #e6e6e6; }"
            "QCalendarWidget QMenu { background: #2b2b2b; color: #e6e6e6; }"
            "QCalendarWidget QWidget { background: #1e1e1e; color: #e6e6e6; }"
        )
    else:
        qss = (
            "QCalendarWidget QAbstractItemView { selection-background-color: #d9e7f7;"
            " selection-color: #1a1a1a; color: #1a1a1a; }"
        )
    if qss:
        try:
            cal = date_edit.calendarWidget()
            cal.setStyleSheet(qss)
            cal.setMinimumSize(320, 260)
        except Exception:
            pass
    # 使 QDateEdit 自身的文本在暗色下可读
    date_edit.setStyleSheet(
        "QDateEdit { color: #e6e6e6; }" if dark else "QDateEdit { color: #1a1a1a; }"
    )


class _TodoItemDelegate(QtWidgets.QStyledItemDelegate):
    """便签表格列内联编辑器：类别/优先级/状态用下拉框，标题用不全选的单行框。"""

    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def _make_combo(self, parent, rows, default_index=0):
        editor = QtWidgets.QComboBox(parent)
        for label, data in rows:
            editor.addItem(label, data)
        editor.setCurrentIndex(default_index)
        editor.setFrame(False)
        return editor

    def createEditor(self, parent, option, index):
        col = index.column()
        if col == 2:  # 类别
            editor = QtWidgets.QComboBox(parent)
            editor.setEditable(True)
            editor.addItem("")
            for c in get_categories():
                editor.addItem(c)
            editor.lineEdit().setFrame(False)
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        if col == 3:  # 优先级
            labels = [(PRIORITY_LABELS[i], i) for i in (0, 1, 2, 3)]
            editor = self._make_combo(parent, labels)
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        if col == 5:  # 状态
            editor = self._make_combo(parent, [("待办", 0), ("已完成", 1)])
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        col = index.column()
        if col == 2:
            i = editor.findText(index.data() or "")
            editor.setCurrentIndex(i if i >= 0 else 0)
        elif col == 3:
            val = index.data(QtCore.Qt.UserRole)
            for i in range(editor.count()):
                if editor.itemData(i) == val:
                    editor.setCurrentIndex(i)
                    break
        elif col == 5:
            done = index.data(QtCore.Qt.UserRole)
            editor.setCurrentIndex(1 if done else 0)
        else:
            super().setEditorData(editor, index)
            # 不在进入编辑时全选高亮（避免文字看不清），光标移到末尾
            le = getattr(editor, "lineEdit", None)
            target = le() if le else editor
            if isinstance(target, QtWidgets.QLineEdit):
                target.deselect()

    def setModelData(self, editor, model, index):
        col = index.column()
        item = self.table.item(index.row(), index.column())
        if col == 2:
            text = (editor.currentText() or "").strip()
            if item is not None:
                item.setText(text)
            else:
                model.setData(index, text)
        elif col == 3:
            val = editor.currentData()
            if item is not None:
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(PRIORITY_LABELS.get(val, "?"))
                item.setForeground(QtGui.QColor(PRIORITY_COLORS.get(val, "#888")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
        elif col == 5:
            val = editor.currentData()
            if item is not None:
                item.setData(QtCore.Qt.UserRole, val)
                item.setText("已完成" if val else "待办")
                item.setForeground(QtGui.QColor("#27ae60" if val else "#3498db"))
        else:
            super().setModelData(editor, model, index)

    def _commit_current(self):
        try:
            self.commitData.emit(self.sender())
        except Exception:
            pass


# ── 独立页面 ──────────────────────────────────────────────────────────

def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    toolbar = QtWidgets.QHBoxLayout()

    search_input = QtWidgets.QLineEdit()
    search_input.setPlaceholderText("搜索标题/内容...")
    search_input.setMaximumWidth(180)
    toolbar.addWidget(search_input)

    combo_filter = ComboBox()
    combo_filter.addItem("全部", userData="all")
    combo_filter.addItem("未完成", userData="pending")
    combo_filter.addItem("已完成", userData="done")
    combo_filter.setMinimumWidth(80)
    toolbar.addWidget(combo_filter)

    combo_category = ComboBox()
    combo_category.addItem("全部分类", userData="")
    combo_category.setMinimumWidth(100)
    toolbar.addWidget(combo_category)

    combo_order = ComboBox()
    combo_order.addItem("按时间", userData="created_at")
    combo_order.addItem("按优先级", userData="priority")
    combo_order.addItem("按截止日", userData="due_date")
    combo_order.setMinimumWidth(80)
    toolbar.addWidget(combo_order)

    toolbar.addStretch(1)

    btn_add = PrimaryPushButton("新增")
    toolbar.addWidget(btn_add)
    btn_edit = PushButton("编辑")
    toolbar.addWidget(btn_edit)
    btn_toggle = PushButton("完成/撤销")
    toolbar.addWidget(btn_toggle)
    btn_copy = PushButton("复制")
    toolbar.addWidget(btn_copy)
    btn_del = PushButton("删除")
    toolbar.addWidget(btn_del)
    lay.addLayout(toolbar)

    table = QtWidgets.QTableWidget()
    table.setColumnCount(7)
    table.setHorizontalHeaderLabels(["标题", "内容", "类别", "优先级", "截止日期", "状态", "创建时间"])
    from ui.adaptive_table import make_adaptive_table
    _stretch = make_adaptive_table(table)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    _sel_pal = table.palette()
    _sel_pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(128, 128, 128, 40))
    _sel_pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    table.setPalette(_sel_pal)
    table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { padding: 3px; }"
        "QTableWidget::item:hover { background: transparent; }"
        "QTableWidget::item:selected { background: rgba(128,128,128,0.12); }"
        "QTableWidget::item:selected:hover { background: rgba(128,128,128,0.12); }"
    )
    table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    lay.addWidget(table, 1)

    status_row = QtWidgets.QHBoxLayout()
    lb_count = BodyLabel("共 0 项")
    status_row.addWidget(lb_count)
    status_row.addStretch(1)
    lay.addLayout(status_row)

    _all_todos = []
    _suppress_item_change = False
    _editing = False

    def refresh():
        nonlocal _all_todos, _suppress_item_change
        _suppress_item_change = True
        done_filter = None
        fd = combo_filter.currentData()
        if fd == "pending":
            done_filter = 0
        elif fd == "done":
            done_filter = 1
        keyword = search_input.text().strip() or None
        order = combo_order.currentData()
        cat = combo_category.currentData() or None
        _all_todos = get_todos(done=done_filter, keyword=keyword, order=order, category=cat)

        table.setRowCount(len(_all_todos))
        now = datetime.now().date()
        for i, t in enumerate(_all_todos):
            title_item = QtWidgets.QTableWidgetItem(t["title"])
            title_item.setFlags(title_item.flags() | QtCore.Qt.ItemIsEditable)
            if t["done"]:
                f = title_item.font()
                f.setStrikeOut(True)
                title_item.setFont(f)
            table.setItem(i, 0, title_item)

            content_item = QtWidgets.QTableWidgetItem(t["content"][:80])
            content_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            content_item.setToolTip(t["content"])
            content_item.setForeground(QtGui.QColor("#555"))
            table.setItem(i, 1, content_item)

            cat_item = QtWidgets.QTableWidgetItem(t["category"])
            cat_item.setFlags(cat_item.flags() | QtCore.Qt.ItemIsEditable)
            cat_item.setForeground(QtGui.QColor("#8e44ad"))
            table.setItem(i, 2, cat_item)

            pri_label = PRIORITY_LABELS.get(t["priority"], "?")
            pri_item = QtWidgets.QTableWidgetItem(pri_label)
            pri_item.setData(QtCore.Qt.UserRole, t["priority"])
            pri_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            pri_item.setForeground(QtGui.QColor(PRIORITY_COLORS.get(t["priority"], "#888")))
            font = pri_item.font()
            font.setBold(True)
            pri_item.setFont(font)
            table.setItem(i, 3, pri_item)

            due_str = t["due_date"] or ""
            due_item = QtWidgets.QTableWidgetItem(due_str)
            if t["due_date"] and not t["done"]:
                try:
                    due = datetime.strptime(t["due_date"], "%Y-%m-%d").date()
                    days = (due - now).days
                    if days < 0:
                        due_item.setForeground(QtGui.QColor("#e74c3c"))
                    elif days <= 1:
                        due_item.setForeground(QtGui.QColor("#e67e22"))
                except ValueError:
                    pass
            table.setItem(i, 4, due_item)

            status_item = QtWidgets.QTableWidgetItem("已完成" if t["done"] else "待办")
            status_item.setData(QtCore.Qt.UserRole, t["done"])
            status_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            status_item.setForeground(QtGui.QColor("#27ae60" if t["done"] else "#3498db"))
            table.setItem(i, 5, status_item)

            table.setItem(i, 6, QtWidgets.QTableWidgetItem(t["created_at"][:16]))

        lb_count.setText(f"共 {len(_all_todos)} 项")
        _suppress_item_change = False

    def get_selected_id():
        rows = set(idx.row() for idx in table.selectedIndexes())
        if not rows:
            return None
        row = min(rows)
        if row < len(_all_todos):
            return _all_todos[row]["id"]
        return None

    def on_add():
        dlg = _TodoEditDialog(w)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            data = dlg.get_data()
            if data["title"].strip():
                add_todo(data["title"], data["content"], data["priority"], data["due_date"], data["category"])
                refresh()

    def on_edit():
        tid = get_selected_id()
        if tid is None:
            return
        todos = get_todos()
        todo = next((t for t in todos if t["id"] == tid), None)
        if not todo:
            return
        dlg = _TodoEditDialog(w, todo)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            data = dlg.get_data()
            update_todo(tid, **data)
            refresh()

    def on_toggle():
        tid = get_selected_id()
        if tid is None:
            return
        todos = get_todos()
        todo = next((t for t in todos if t["id"] == tid), None)
        if todo:
            update_todo(tid, done=0 if todo["done"] else 1)
            refresh()

    def _selected_rows():
        return sorted({idx.row() for idx in table.selectedIndexes()})

    def on_copy():
        rows = _selected_rows()
        if not rows:
            return
        parts = []
        for row in rows:
            if row >= len(_all_todos):
                continue
            t = _all_todos[row]
            line = t["title"]
            if t["content"]:
                line += " - " + t["content"]
            if t["category"]:
                line += f" [{t['category']}]"
            parts.append(line)
        if parts:
            QtWidgets.QApplication.clipboard().setText("\n".join(parts))
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success("已复制", f"已复制 {len(parts)} 项到剪贴板",
                            parent=w, position=InfoBarPosition.TOP_RIGHT, duration=2000)

    def on_delete():
        rows = _selected_rows()
        if not rows:
            return
        reply = QtWidgets.QMessageBox.question(
            w, "确认删除", f"确定删除选中的 {len(rows)} 项？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            for row in sorted(rows, reverse=True):
                if row < len(_all_todos):
                    delete_todo(_all_todos[row]["id"])
            refresh()

    _defer_timer = QtCore.QTimer()
    _defer_timer.setSingleShot(True)
    _defer_timer.setInterval(0)
    _defer_timer.timeout.connect(refresh)

    def request_refresh():
        # 延迟到当前编辑/信号完成后刷新，避免在 delegate 编辑中途销毁条目
        _defer_timer.start()

    def on_item_changed(item):
        nonlocal _suppress_item_change
        if _suppress_item_change:
            return
        row = item.row()
        if row >= len(_all_todos):
            return
        tid = _all_todos[row]["id"]
        col = item.column()
        if col == 0:
            update_todo(tid, title=item.text().strip())
        elif col == 2:
            update_todo(tid, category=item.text().strip())
        elif col == 3:
            update_todo(tid, priority=item.data(QtCore.Qt.UserRole))
        elif col == 5:
            update_todo(tid, done=item.data(QtCore.Qt.UserRole))
        request_refresh()

    btn_add.clicked.connect(on_add)
    btn_edit.clicked.connect(on_edit)
    btn_toggle.clicked.connect(on_toggle)
    btn_copy.clicked.connect(on_copy)
    btn_del.clicked.connect(on_delete)
    search_input.returnPressed.connect(refresh)
    combo_filter.currentIndexChanged.connect(refresh)
    combo_order.currentIndexChanged.connect(refresh)
    combo_category.currentIndexChanged.connect(refresh)
    table.itemChanged.connect(on_item_changed)

    def refresh_categories(keep_selection=False):
        current = combo_category.currentData() or ""
        combo_category.blockSignals(True)
        combo_category.clear()
        combo_category.addItem("全部分类", userData="")
        for c in get_categories():
            combo_category.addItem(c, userData=c)
        idx = combo_category.findData(current)
        combo_category.setCurrentIndex(idx if idx >= 0 else 0)
        combo_category.blockSignals(False)

    table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    table.customContextMenuRequested.connect(
        lambda pos: _page_context_menu(pos, table, _all_todos, refresh, on_copy))
    table.setItemDelegate(_TodoItemDelegate(table))
    # 调高行高，避免文字底部被裁剪
    table.verticalHeader().setDefaultSectionSize(30)

    _click_timer = QtCore.QTimer()
    _click_timer.setSingleShot(True)
    _click_timer.setInterval(220)

    def _do_inline_edit(row, col):
        if _col_editable(col) and row < len(_all_todos):
            item = table.item(row, col)
            if item is not None and (item.flags() & QtCore.Qt.ItemIsEditable):
                table.editItem(item)

    def _col_editable(col):
        # 内容列(1)用完整编辑框（多行），其余可下拉/单行编辑
        return col in (0, 2, 3, 5)

    def _on_cell_clicked(row, col):
        # 内容列：单击直接打开完整编辑对话框（支持多行编辑）
        if col == 1 and 0 <= row < len(_all_todos):
            tid = _all_todos[row]["id"]
            todos = get_todos()
            todo = next((t for t in todos if t["id"] == tid), None)
            if todo:
                dlg = _TodoEditDialog(w, todo)
                if dlg.exec() == QtWidgets.QDialog.Accepted:
                    data = dlg.get_data()
                    update_todo(tid, **data)
                    refresh()
            return
        # 单击延迟触发行内编辑，等待可能到来的双击（打开详情）
        try:
            _click_timer.timeout.disconnect()
        except RuntimeError:
            pass
        _click_timer.timeout.connect(lambda: _do_inline_edit(row, col))
        _click_timer.start()

    def _on_cell_double_clicked(row, col):
        _click_timer.stop()
        on_edit()

    table.cellClicked.connect(_on_cell_clicked)
    table.cellDoubleClicked.connect(_on_cell_double_clicked)

    refresh_categories()
    refresh()
    owner._page_refresh = lambda: (refresh_categories(), refresh())
    return w


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

    action = menu.exec_(table.mapToGlobal(pos))
    if not action:
        return
    if action == act_toggle:
        update_todo(todo["id"], done=0 if todo["done"] else 1)
        refresh()
    elif action == act_copy:
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
    elif action == act_high:
        update_todo(todo["id"], priority=3)
        refresh()
    elif action == act_hi:
        update_todo(todo["id"], priority=2)
        refresh()
    elif action == act_mid:
        update_todo(todo["id"], priority=1)
        refresh()
    elif action == act_low:
        update_todo(todo["id"], priority=0)
        refresh()
    elif action == act_del:
        delete_todo(todo["id"])
        refresh()


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
