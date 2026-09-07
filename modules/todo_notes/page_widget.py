"""todo_notes 独立页面：_make_page_widget（单函数原子切片，超 250 行豁免）。"""
from datetime import datetime
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .constants import (COL_CATEGORY, COL_CHECK, COL_CONTENT, COL_CREATED,
                        COL_DUE, COL_PRIORITY, COL_STATUS, COL_TITLE,
                        CONTENT_COL_PAD, CONTENT_MAX_LINES,
                        PRIORITY_COLORS, PRIORITY_LABELS)
from ..todo_store import (add_todo, delete_todo, get_categories,
                           get_todos, update_todo)
from .delegate import _TodoItemDelegate
from .select_all_header import _SelectAllHeader
from .page_helpers import (_page_context_menu, _TodoEditDialog,
                            _maybe_reset_done_on_content_change)
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
    table.setColumnCount(8)
    table.setHorizontalHeaderLabels(["", "标题", "内容", "类别", "优先级", "截止日期", "状态", "创建时间"])
    # 复选框列(首列)标题栏自定义表头：绘制全选复选框，替代原工具栏「全选」按钮
    _sel_header = _SelectAllHeader(table)
    table.setHorizontalHeader(_sel_header)
    from ui.adaptive_table import make_adaptive_table
    # 内容列是折行/弹性列：限其最多占视口一半宽，避免按原始全文测宽后吃满窗口、
    # 挤压标题/创建时间等窄列导致其内容被截断/换行。
    _stretch = make_adaptive_table(table, width_caps={COL_CONTENT: 0.5},
                                   min_widths={COL_CHECK: table.fontMetrics().horizontalAdvance("取消") + 24})
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

    def _fit_content_heights():
        # 按当前内容列宽为每行重算折行显示高度（最多 CONTENT_MAX_LINES 行）。
        # 用于：refresh 后、自适应列宽首次落定（reflow）后、以及用户拖拽内容列宽时。
        if _editing:
            return
        try:
            fm = table.fontMetrics()
            col_w = max(10, table.columnWidth(COL_CONTENT) - CONTENT_COL_PAD)
            sp = fm.lineSpacing()
            for i in range(table.rowCount()):
                it = table.item(i, COL_CONTENT)
                text = it.text() if it else ""
                wrapped = _TodoItemDelegate._wrap_lines(text, fm, col_w)
                shown = min(max(1, len(wrapped)), CONTENT_MAX_LINES)
                table.setRowHeight(i, shown * (sp + 2) + 6)
        except Exception:
            pass

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
        _all_todos = get_todos(done=done_filter, keyword=keyword, order=order or "created_at", category=cat)

        table.setRowCount(len(_all_todos))
        now = datetime.now().date()
        for i, t in enumerate(_all_todos):
            check_item = QtWidgets.QTableWidgetItem()
            check_item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            check_item.setCheckState(QtCore.Qt.Unchecked)
            table.setItem(i, COL_CHECK, check_item)

            title_item = QtWidgets.QTableWidgetItem(t["title"])
            title_item.setFlags(title_item.flags() | QtCore.Qt.ItemIsEditable)
            if t["done"]:
                f = title_item.font()
                f.setStrikeOut(True)
                title_item.setFont(f)
            table.setItem(i, COL_TITLE, title_item)

            content_item = QtWidgets.QTableWidgetItem(t["content"])
            content_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            content_item.setForeground(QtGui.QColor("#555"))
            table.setItem(i, COL_CONTENT, content_item)

            cat_item = QtWidgets.QTableWidgetItem(t["category"])
            cat_item.setFlags(cat_item.flags() | QtCore.Qt.ItemIsEditable)
            cat_item.setForeground(QtGui.QColor("#8e44ad"))
            table.setItem(i, COL_CATEGORY, cat_item)

            pri_label = PRIORITY_LABELS.get(t["priority"], "?")
            pri_item = QtWidgets.QTableWidgetItem(pri_label)
            pri_item.setData(QtCore.Qt.UserRole, t["priority"])
            pri_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            pri_item.setForeground(QtGui.QColor(PRIORITY_COLORS.get(t["priority"], "#888")))
            font = pri_item.font()
            font.setBold(True)
            pri_item.setFont(font)
            table.setItem(i, COL_PRIORITY, pri_item)

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
            table.setItem(i, COL_DUE, due_item)

            status_item = QtWidgets.QTableWidgetItem("已完成" if t["done"] else "待办")
            status_item.setData(QtCore.Qt.UserRole, t["done"])
            status_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            status_item.setForeground(QtGui.QColor("#27ae60" if t["done"] else "#3498db"))
            table.setItem(i, COL_STATUS, status_item)

            table.setItem(i, COL_CREATED, QtWidgets.QTableWidgetItem(t["created_at"][:16]))

        # 数据填充完后按当前内容列宽统一重算行高（首次打开时列宽可能尚未被自适应落定）
        _fit_content_heights()
        lb_count.setText(f"共 {len(_all_todos)} 项")
        _suppress_item_change = False
        _update_select_all_state()

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
            _maybe_reset_done_on_content_change(tid, todo["content"], data.get("content", ""))
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

    def _checked_rows():
        rows = []
        for i in range(table.rowCount()):
            it = table.item(i, COL_CHECK)
            if it is not None and it.checkState() == QtCore.Qt.Checked:
                rows.append(i)
        return rows

    _check_anchor = [-1]   # shift 区间基准行（上一次普通/ctrl 点击的行）

    def _on_check_click(row, ctrl, shift):
        """复选框行点击：普通切换、ctrl 单独切换、shift 区间填充，并联动行选择。"""
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_CHECK)
        if item is None:
            return
        target_rows = [row]
        if shift and _check_anchor[0] >= 0:
            lo, hi = sorted((_check_anchor[0], row))
            target_rows = list(range(lo, hi + 1))
        table.blockSignals(True)
        try:
            if shift and _check_anchor[0] >= 0:
                ref = table.item(_check_anchor[0], COL_CHECK)
                state = ref.checkState() if ref is not None else QtCore.Qt.Unchecked
            else:
                state = (QtCore.Qt.Unchecked
                         if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)
            for r in target_rows:
                it = table.item(r, COL_CHECK)
                if it is not None:
                    it.setCheckState(state)
        finally:
            table.blockSignals(False)
        if not shift:
            _check_anchor[0] = row
        # 持久化每个被改动行的 done 状态
        for r in target_rows:
            if r < len(_all_todos):
                update_todo(_all_todos[r]["id"],
                            done=1 if table.item(r, COL_CHECK).checkState() == QtCore.Qt.Checked else 0)
        # 联动行选择：选中本次受影响的行，保证批复制等操作与之对齐
        sel_model = table.selectionModel()
        if sel_model is not None:
            from PySide6.QtCore import QItemSelection, QItemSelectionModel
            sel_model.clearSelection()
            tl = table.model().index(min(target_rows), 0)
            br = table.model().index(max(target_rows), table.columnCount() - 1)
            sel_model.select(QItemSelection(tl, br), QItemSelectionModel.SelectionFlag.Select)  # type: ignore[reportAttributeAccessIssue]
        _update_select_all_state()

    def on_copy():
        rows = _checked_rows() or _selected_rows()
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
        if col == COL_TITLE:
            update_todo(tid, title=item.text().strip())
            request_refresh()
        elif col == COL_CONTENT:
            update_todo(tid, content=item.text().strip())
            update_todo(tid, done=0)
            request_refresh()
        elif col == COL_CATEGORY:
            update_todo(tid, category=item.text().strip())
            request_refresh()
        elif col == COL_PRIORITY:
            update_todo(tid, priority=item.data(QtCore.Qt.UserRole))
            request_refresh()
        elif col == COL_STATUS:
            update_todo(tid, done=item.data(QtCore.Qt.UserRole))
            request_refresh()

    def _on_select_all_toggled(checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for i in range(table.rowCount()):
            it = table.item(i, COL_CHECK)
            if it is not None:
                it.setCheckState(state)

    def _update_select_all_state():
        if table.rowCount() == 0:
            _sel_header.set_all_checked(False)
            return
        all_on = all(
            (table.item(i, COL_CHECK) is not None
             and table.item(i, COL_CHECK).checkState() == QtCore.Qt.Checked)
            for i in range(table.rowCount())
        )
        _sel_header.set_all_checked(all_on)

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
    _sel_header._toggled.connect(_on_select_all_toggled)

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
    _delegate = _TodoItemDelegate(table)
    _delegate.check_click_handler = _on_check_click  # type: ignore[reportAttributeAccessIssue]
    table.setItemDelegate(_delegate)
    # 调高行高，避免文字底部被裁剪
    table.verticalHeader().setDefaultSectionSize(30)

    _click_timer = QtCore.QTimer()
    _click_timer.setSingleShot(True)
    _click_timer.setInterval(220)
    _pending_edit: list[tuple[int, int] | None] = [None]

    def _do_inline_edit(row, col):
        if not (_col_editable(col) and row < len(_all_todos)):
            return
        item = table.item(row, col)
        if item is None or not (item.flags() & QtCore.Qt.ItemIsEditable):
            return
        # 需求：进入快速编辑时不高亮被编辑的那一行（清空行选择，避免行被蓝/灰高亮）
        table.clearSelection()
        _delegate._editing_cell = (row, col)  # type: ignore[reportAttributeAccessIssue]
        if col == COL_CONTENT:
            _expand_row_for_content(row, item.text())
        table.editItem(item)
        # 立即重绘，清除底层原文字，避免半透明编辑器漏出旧字
        try:
            table.viewport().update()
        except Exception:
            pass

    def _expand_row_for_content(row, text):
        # 进入内容多行编辑前，按内容完整折行高度展开整行，保证全部可见
        default_h = table.verticalHeader().defaultSectionSize()
        try:
            col_w = table.columnWidth(COL_CONTENT) - CONTENT_COL_PAD
        except Exception:
            col_w = 200
        fm = table.fontMetrics()
        try:
            total = len(_TodoItemDelegate._wrap_lines(text or "", fm, max(10, col_w)))
        except Exception:
            total = 1
        height = max(default_h, total * (fm.lineSpacing() + 2) + 6)
        table.setRowHeight(row, height)

    def _col_editable(col):
        # 复选框列除外，其余可编辑列支持单击行内编辑；内容列用多行编辑框
        return col in (COL_TITLE, COL_CONTENT, COL_CATEGORY, COL_PRIORITY, COL_STATUS)

    def _on_cell_clicked(row, col):
        # 单击延迟触发行内编辑，等待可能到来的双击（打开详情）
        _click_timer.stop()
        _pending_edit[0] = (row, col)
        _click_timer.start()

    def _on_cell_double_clicked(row, col):
        _click_timer.stop()
        _pending_edit[0] = None
        on_edit()

    _click_timer.timeout.connect(lambda: _do_inline_edit(*_pending_edit[0]) if _pending_edit[0] else None)

    table.cellClicked.connect(_on_cell_clicked)
    table.cellDoubleClicked.connect(_on_cell_double_clicked)

    refresh_categories()
    refresh()
    # 内容列宽变化（自适应 reflow 首次落定、窗口缩放、用户拖拽）时按最新列宽重算行高，
    # 避免首次打开时所有行都按窄列宽折行成 6 行，点击后才自适应到实际行数。
    table.horizontalHeader().sectionResized.connect(
        lambda logical, *_a: _fit_content_heights() if logical == COL_CONTENT else None)
    # 透明表格滚动多行内容时，Qt 的部分重绘可能残留旧文字描边/轮廓；
    # 滚动即整块刷新视口，即时清除残留、避免“文字的描边还在”。
    table.verticalScrollBar().valueChanged.connect(lambda *_: table.viewport().update())
    table.horizontalScrollBar().valueChanged.connect(lambda *_: table.viewport().update())
    owner._page_refresh = lambda: (refresh_categories(), refresh())
    return w
