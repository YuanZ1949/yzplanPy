"""todo_notes 独立页面：_make_page_widget（单函数原子切片，超 250 行豁免）。"""
from datetime import datetime
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing, theme_palette
from .constants import (COL_CATEGORY, COL_CHECK, COL_CONTENT, COL_CREATED,
                        COL_DUE, COL_PRIORITY, COL_STATUS, COL_TITLE,
                        badge_edit_qss, badge_overlay_qss, content_row_height,
                        category_color, editor_qss, PRIORITY_LABELS,
                        priority_color, status_color)
from ..todo_store import (add_todo, delete_todo, get_categories,
                           get_or_create_status, get_statuses,
                           get_todos, set_todos_done, update_todo)
from .delegate import _BADGE_COLS, _TodoItemDelegate, _widget_focused
from .select_all_header import _SelectAllHeader
from .page_helpers import (_page_context_menu, _TodoEditDialog,
                            _maybe_reset_done_on_content_change)
from .tag_manager import _TagManagerDialog
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
    search_input.setObjectName("todo_search_input")
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
    btn_tags = PushButton("标签管理")
    toolbar.addWidget(btn_tags)
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
    # owner.context.config 存在则启用列宽持久化；缺失（自定义 owner/测试）则仅内存自适应。
    _cfg = getattr(getattr(owner, "context", None), "config", None)
    _stretch = make_adaptive_table(table, width_caps={COL_CONTENT: 0.5},
                                   min_widths={COL_CHECK: table.fontMetrics().horizontalAdvance("取消") + 24},
                                   persist_key="todo.table_widths",
                                   config=_cfg)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(False)
    table.verticalHeader().setVisible(False)
    _sel_pal = table.palette()
    _sel_pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(128, 128, 128, 40))
    _sel_pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    table.setPalette(_sel_pal)
    _p = theme_palette()
    _sz = sizing()
    table.setStyleSheet(
        f"QTableWidget {{ border: 1px solid {_p['border_strong']}; background: transparent;"
        f" gridline-color: {_p['border_strong']}; border-radius: {_sz['radius_lg']}px; }}"
        f"QTableWidget::item {{ padding: {_sz['todo_table_item_padding']}; }}"
        f"QTableWidget::item:hover {{ background: {_p['bg_hover']}; }}"
        f"QTableWidget::item:selected {{ background: {_p['todo_table_sel_bg']}; }}"
        f"QTableWidget::item:selected:hover {{ background: {_p['todo_table_sel_bg']}; }}"
        f"QHeaderView::section {{ border-bottom: 1px solid {_p['border_strong']}; }}"
        f"QHeaderView::section:first {{ border-top-left-radius: {_sz['radius_lg']}px; }}"
        f"QHeaderView::section:last {{ border-top-right-radius: {_sz['radius_lg']}px; }}"
    )
    # 表格 viewport 不画不透明底色：圆角边框外的四角透出父容器背景（无直角残留）
    table.viewport().setAutoFillBackground(False)
    table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    lay.addWidget(table, 1)

    status_row = QtWidgets.QHBoxLayout()
    lb_count = BodyLabel("共 0 项")
    status_row.addWidget(lb_count)
    status_row.addStretch(1)
    lay.addLayout(status_row)

    _all_todos = []
    _suppress_item_change = False
    _status_map = {}

    def _fit_content_heights():
        # 按当前内容列宽为每行重算折行显示高度（最多 CONTENT_SAFE_MAX_LINES 行，安全上限）。
        # 用于：refresh 后、自适应列宽首次落定（reflow）后、以及用户拖拽内容列宽时。
        # 与编辑器共用 content_row_height（同一 chrome/折行引擎），显示态与编辑态不会漂移。
        try:
            col_w = table.columnWidth(COL_CONTENT)
            for i in range(table.rowCount()):
                it = table.item(i, COL_CONTENT)
                text = it.text() if it else ""
                table.setRowHeight(i, content_row_height(text, table.font(), col_w))
        except Exception:
            pass

    def refresh():
        nonlocal _all_todos, _suppress_item_change, _status_map
        # 表格可能已在延迟刷新挂起期间被销毁（窗口关闭）：直接返回
        try:
            table.rowCount()
        except RuntimeError:
            return
        _suppress_item_change = True
        # 重建前销毁全部常驻编辑器（避免旧编辑器残留/泄漏）
        _destroy_cell_widgets()
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
        table._all_todos = _all_todos  # 测试钩子：暴露当前内存行（T18 数据准确性核对）
        _status_map = {s["id"]: s for s in get_statuses()}
        # 状态/类别颜色缓存失效：反映标签管理/右键改色后的新颜色
        _delegate.invalidate_status_cache()

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
            content_item.setForeground(QtGui.QColor(_p["text_secondary"]))
            table.setItem(i, COL_CONTENT, content_item)

            cat_item = QtWidgets.QTableWidgetItem(t["category"])
            cat_item.setFlags(cat_item.flags() | QtCore.Qt.ItemIsEditable)
            cat_item.setForeground(QtGui.QColor(category_color(t["category"]) or _p["todo_category"]))
            table.setItem(i, COL_CATEGORY, cat_item)

            pri_label = PRIORITY_LABELS.get(t["priority"], "?")
            pri_item = QtWidgets.QTableWidgetItem(pri_label)
            pri_item.setData(QtCore.Qt.UserRole, t["priority"])
            pri_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            pri_item.setForeground(QtGui.QColor(priority_color(t["priority"])))
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
                        due_item.setForeground(QtGui.QColor(_p["danger"]))
                    elif days <= 1:
                        due_item.setForeground(QtGui.QColor(_p["warning"]))
                except ValueError:
                    pass
            table.setItem(i, COL_DUE, due_item)

            st = _status_map.get(t["status_id"])
            status_item = QtWidgets.QTableWidgetItem(st["name"] if st else "待办")
            status_item.setData(QtCore.Qt.UserRole, t["status_id"])
            status_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            status_item.setForeground(QtGui.QColor(status_color(st)))
            table.setItem(i, COL_STATUS, status_item)

            table.setItem(i, COL_CREATED, QtWidgets.QTableWidgetItem(t["created_at"][:16]))

        # 数据填充完后按当前内容列宽统一重算行高（首次打开时列宽可能尚未被自适应落定）
        _fit_content_heights()
        lb_count.setText(f"共 {len(_all_todos)} 项")
        _suppress_item_change = False
        _update_select_all_state()
        # 为可见行创建常驻编辑器
        _sync_cell_widgets()

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
                add_todo(data["title"], data["content"], data["priority"],
                         data["due_date"], data["category"],
                         status_id=data.get("status_id"))
                refresh_categories()
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
            _maybe_reset_done_on_content_change(tid, todo["content"], data.get("content", ""))
            refresh_categories()
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

    def _sync_row_from_db(r):
        """按 DB 真值同步第 r 行的内存状态与显示（勾选/全选/改状态后调用）。

        done 的显示态由状态列 + 标题删除线 + 行背景（delegate 按 status_id
        UserRole 绘制）表达。勾选/全选只写 done、改状态只写 status_id 时，
        DB 靠 _migrate_statuses 自愈，但内存 _all_todos 与状态列会 stale——
        这里以 DB 为唯一真源重读该行并同步显示，避免 UI 与 DB 不一致。
        """
        if r >= len(_all_todos):
            return
        fresh = next((t for t in get_todos() if t["id"] == _all_todos[r]["id"]), None)
        if fresh is None:
            return
        _all_todos[r]["done"] = fresh["done"]
        _all_todos[r]["status_id"] = fresh["status_id"]
        st = _status_map.get(fresh["status_id"])
        table.blockSignals(True)
        try:
            st_item = table.item(r, COL_STATUS)
            if st_item is not None:
                st_item.setData(QtCore.Qt.UserRole, fresh["status_id"])
                st_item.setText(st["name"] if st else "待办")
                st_item.setForeground(QtGui.QColor(status_color(st)))
            title_item = table.item(r, COL_TITLE)
            if title_item is not None:
                f = title_item.font()
                f.setStrikeOut(bool(fresh["done"]))
                title_item.setFont(f)
        finally:
            table.blockSignals(False)
        st_combo = table.cellWidget(r, COL_STATUS)
        if st_combo is not None:
            idx = st_combo.findData(fresh["status_id"])
            if idx >= 0:
                st_combo.setCurrentIndex(idx)

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
                _sync_row_from_db(r)
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

    def on_tag_manager():
        dlg = _TagManagerDialog(w)
        dlg.exec()
        # 标签管理可能新增/改名/删除类别：刷新工具栏筛选与表格（refresh 重建
        # 可见行下拉时从 get_categories() 重读，故行内选项同步）。
        refresh_categories()
        refresh()

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
            # 列修改不重置 done（用户裁决范围 A，仅内容列重置）
            update_todo(tid, title=item.text().strip())
            _all_todos[row]["title"] = item.text().strip()
        elif col == COL_CONTENT:
            # 内容修改说明可能有新增事项：done 与 status_id 同步归零（todo 2 后
            # 状态列渲染由 status_id 驱动，仅置 done=0 会让状态显示不变）
            todo_sid = next(
                (sid for sid, s in _status_map.items() if s["name"] == "待办"), None
            )
            if todo_sid is None:
                todo_sid = get_or_create_status("待办")
            update_todo(tid, content=item.text().strip(), done=0, status_id=todo_sid)
            _all_todos[row]["content"] = item.text().strip()
            _all_todos[row]["done"] = 0
            _all_todos[row]["status_id"] = todo_sid
            # 同步状态列显示（表格项 + 常驻下拉），让用户立即看到状态回到「待办」
            st_item = table.item(row, COL_STATUS)
            if st_item is not None:
                st_item.setData(QtCore.Qt.UserRole, todo_sid)
                st_item.setText("待办")
                # 新状态可能尚未进 _status_map（get_or_create_status 新建）：.get()
                # 防 KeyError，缺失时回落 text_secondary。
                _st = _status_map.get(todo_sid)
                st_item.setForeground(QtGui.QColor(
                    status_color(_st) if _st else _p["text_secondary"]))
            st_combo = table.cellWidget(row, COL_STATUS)
            if st_combo is not None:
                idx = st_combo.findData(todo_sid)
                if idx >= 0:
                    st_combo.setCurrentIndex(idx)
            _fit_content_heights()
        elif col == COL_CATEGORY:
            # 列修改不重置 done（用户裁决范围 A，仅内容列重置）
            update_todo(tid, category=item.text().strip())
            _all_todos[row]["category"] = item.text().strip()
        elif col == COL_PRIORITY:
            # 列修改不重置 done（用户裁决范围 A，仅内容列重置）
            update_todo(tid, priority=item.data(QtCore.Qt.UserRole))
            _all_todos[row]["priority"] = item.data(QtCore.Qt.UserRole)
        elif col == COL_STATUS:
            update_todo(tid, status_id=item.data(QtCore.Qt.UserRole))
            _sync_row_from_db(row)
        elif col == COL_DUE:
            update_todo(tid, due_date=item.text().strip() or None)
            _all_todos[row]["due_date"] = item.text().strip() or None

    def _on_select_all_toggled(checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        ids = []
        for i in range(table.rowCount()):
            it = table.item(i, COL_CHECK)
            if it is not None:
                it.setCheckState(state)
                if i < len(_all_todos):
                    ids.append(_all_todos[i]["id"])
        # 全选/取消全选持久化到数据库（批量单条 UPDATE，避免 N 次单行写），
        # 否则 refresh() 从 t["done"] 重建行时会丢失勾选状态
        if ids:
            set_todos_done(ids, bool(checked))
            for i in range(len(ids)):
                _sync_row_from_db(i)
        _update_select_all_state()

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
    btn_tags.clicked.connect(on_tag_manager)
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

    _WIDGET_COLS = (COL_TITLE, COL_CONTENT, COL_CATEGORY, COL_PRIORITY, COL_STATUS, COL_DUE)

    class _DblClickFilter(QtCore.QObject):
        """单元格控件上的双击过滤器：双击控件打开编辑对话框（与无控件列一致）。"""

        def __init__(self, row, callback, parent=None):
            super().__init__(parent)
            self._row = row
            self._callback = callback

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.MouseButtonDblClick:
                self._callback(self._row)
                return True
            return super().eventFilter(obj, event)

    def _on_widget_dbl_click(row):
        if row >= len(_all_todos):
            return
        table.selectRow(row)
        on_edit()

    def _on_title_editor_changed(row):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_TITLE)
        if item is None:
            return
        ed = table.cellWidget(row, COL_TITLE)
        if ed is None:
            return
        text = ed.text()
        if item.text() != text:
            item.setText(text)

    def _on_content_editor_changed(row):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_CONTENT)
        if item is None:
            return
        ed = table.cellWidget(row, COL_CONTENT)
        if ed is None:
            return
        text = ed.toPlainText()
        if item.text() != text:
            item.setText(text)

    def _apply_badge_state(ed):
        """按焦点切换选项列 combo 外观：聚焦=可读编辑器，失焦=隐形胶囊层（旧观感）。

        失焦时控件完全隐形，胶囊由 delegate 画在单元格里；聚焦时才显示编辑器，
        保留直接手输新值的能力。状态未变时不重复 setStyleSheet（避免无谓的
        样式重抛光），控件已销毁时安全返回。
        """
        if ed is None:
            return
        try:
            le = ed.lineEdit()
        except AttributeError:
            le = None
        except RuntimeError:
            return
        try:
            focused = bool(ed.hasFocus() or (le is not None and le.hasFocus()))
        except RuntimeError:
            return
        if getattr(ed, "_badge_focused_state", None) == focused:
            return
        ed._badge_focused_state = focused
        try:
            ed.setStyleSheet(badge_edit_qss() if focused else badge_overlay_qss())
        except RuntimeError:
            pass

    def _on_category_committed(row):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_CATEGORY)
        if item is None:
            return
        ed = table.cellWidget(row, COL_CATEGORY)
        if ed is None:
            return
        text = (ed.currentText() or "").strip()
        if item.text() != text:
            item.setText(text)
        _apply_badge_state(ed)
        # 手输新类别已由 item.setText → on_item_changed → update_todo → ensure_category
        # 落库；就地刷新可见行下拉与工具栏筛选，让新类别立即出现。
        _refresh_option_widgets()
        refresh_categories()

    def _on_priority_committed(row):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_PRIORITY)
        if item is None:
            return
        ed = table.cellWidget(row, COL_PRIORITY)
        if ed is None:
            return
        val = ed.currentData()
        if item.data(QtCore.Qt.UserRole) != val:
            item.setData(QtCore.Qt.UserRole, val)
            item.setText(PRIORITY_LABELS.get(val, "?"))
            item.setForeground(QtGui.QColor(priority_color(val)))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        _apply_badge_state(ed)

    def _on_status_committed(row):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_STATUS)
        if item is None:
            return
        ed = table.cellWidget(row, COL_STATUS)
        if ed is None:
            return
        text = (ed.currentText() or "").strip()
        if not text:
            return
        statuses = {s["name"]: s for s in get_statuses()}
        st = statuses.get(text)
        if st is None:
            sid = get_or_create_status(text)
            st = {"id": sid, "name": text, "color": None}
        _apply_badge_state(ed)
        if item.data(QtCore.Qt.UserRole) == st["id"] and item.text() == text:
            return
        item.setData(QtCore.Qt.UserRole, st["id"])
        item.setText(text)
        item.setForeground(QtGui.QColor(status_color(st)))
        _status_map[st["id"]] = st
        _delegate.invalidate_status_cache()
        # 新状态已落库：就地刷新可见行下拉（其它行立即可选），工具栏同步。
        _refresh_option_widgets()
        refresh_categories()

    def _on_due_changed(row, date):
        if row >= len(_all_todos):
            return
        item = table.item(row, COL_DUE)
        if item is None:
            return
        text = date.toString("yyyy-MM-dd") if date.isValid() else ""
        if date.isValid() and date == QtCore.QDate(1900, 1, 1):
            text = ""
        if item.text() != text:
            item.setText(text)

    def _clear_due(row):
        """把截止日期清回「无」（只读日期控件无法直接清空，故提供清除按钮）。"""
        holder = table.cellWidget(row, COL_DUE)
        if holder is None:
            return
        de = holder.findChild(QtWidgets.QDateEdit)
        if de is not None:
            de.blockSignals(True)
            de.setDate(QtCore.QDate(1900, 1, 1))
            de.blockSignals(False)
        _on_due_changed(row, QtCore.QDate(1900, 1, 1))

    class _DueHoverFilter(QtCore.QObject):
        """截止日期单元格悬浮过滤器：进入显示清除键，离开时若鼠标已不在
        holder/子控件内则隐藏。日历弹窗打开或按钮有焦点时保持可见（防闪烁）。

        防抖关键：清除键在鼠标进入 holder 时出现，若鼠标恰好停在按钮将出现的
        右缘，按钮现身会触发一次 holder 的 Leave——此时鼠标仍在 holder 内
        （_mouse_inside 为真），不得隐藏，否则按钮会闪一下又消失。
        """

        def __init__(self, holder, btn, parent=None):
            super().__init__(parent or holder)
            self._holder = holder
            self._btn = btn

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Enter:
                self._btn.setVisible(True)
            elif event.type() == QtCore.QEvent.Leave:
                if self._mouse_inside() or self._keep_visible():
                    return False
                self._btn.setVisible(False)
            return False

        def _mouse_inside(self):
            """鼠标是否仍在 holder（含子控件）范围内。"""
            try:
                local = self._holder.mapFromGlobal(QtGui.QCursor.pos())
                return self._holder.rect().contains(local)
            except RuntimeError:
                return False

        def _keep_visible(self):
            """日历弹窗打开或按钮有焦点时保持可见（防闪烁）。"""
            try:
                if self._btn.hasFocus():
                    return True
                de = self._holder.findChild(QtWidgets.QDateEdit)
                if de is not None:
                    cal = de.calendarWidget()
                    if cal is not None and cal.isVisible():
                        return True
            except RuntimeError:
                pass
            return False

    class _BadgeStateFilter(QtCore.QObject):
        """选项列 combo 的焦点切换：聚焦转编辑器外观，失焦回到隐形胶囊层。

        QComboBox 的焦点可能落在自身或内嵌 QLineEdit（可编辑时），两者都监听。
        同步处理（不用 singleShot 延迟），避免控件销毁后仍有挂起回调。
        失焦时同时恢复鼠标穿透，否则上一行会残留可点控件。
        """

        def __init__(self, editor, parent=None):
            super().__init__(parent or editor)
            self._editor = editor

        def eventFilter(self, obj, event):
            if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.FocusOut):
                if event.type() == QtCore.QEvent.FocusOut:
                    fw = QtWidgets.QApplication.focusWidget()
                    if (fw is self._editor
                            or (fw is not None and self._editor.isAncestorOf(fw))
                            or self._editor.view().isVisible()
                            or (fw is not None
                                and self._editor.view().isAncestorOf(fw))):
                        # 焦点仍在本 combo 的交互范围内（自身/内嵌 lineEdit/
                        # 弹窗视图）——showPopup 会让弹窗视图抢走焦点（Qt 标准
                        # 行为），此时不能撤销编辑态，否则点击后立刻回到胶囊。
                        return False
                _apply_badge_state(self._editor)
                # 聚焦=可交互（解除穿透 / 保持穿透由单击过滤器负责解除），
                # 失焦=恢复穿透（与初值一致），保证同一时刻只有一个可点控件。
                try:
                    self._editor.setAttribute(
                        QtCore.Qt.WA_TransparentForMouseEvents,
                        event.type() == QtCore.QEvent.FocusOut)
                    # 失焦同时退出焦点链：悬浮不再把焦点交给 combo（NoFocus 挡 hover 聚焦）
                    if event.type() == QtCore.QEvent.FocusOut:
                        self._editor.setFocusPolicy(QtCore.Qt.NoFocus)
                except RuntimeError:
                    pass
            return False

    def _ensure_row_widgets(r):
        t = _all_todos[r]
        # 标题
        if table.cellWidget(r, COL_TITLE) is None:
            ed = QtWidgets.QLineEdit(table)
            ed.setFrame(False)
            ed.setStyleSheet(editor_qss())
            ed.setText(t["title"])
            ed.textChanged.connect(lambda _t, r=r: _on_title_editor_changed(r))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            table.setCellWidget(r, COL_TITLE, ed)
        # 内容
        if table.cellWidget(r, COL_CONTENT) is None:
            ed = _delegate._make_content_editor(table, r)
            ed.setPlainText(t["content"])
            # QPlainTextEdit.textChanged 是 0 参信号：lambda 必须 arity-agnostic，
            # 否则每次按键都抛 TypeError（_t 缺参），编辑完全不落库。
            ed.textChanged.connect(lambda *_, r=r: _on_content_editor_changed(r))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            # QPlainTextEdit 的双击投递到它内部的 viewport 子控件，必须同时装上去
            ed.viewport().installEventFilter(
                _DblClickFilter(r, _on_widget_dbl_click, ed.viewport()))
            table.setCellWidget(r, COL_CONTENT, ed)
        # 类别
        if table.cellWidget(r, COL_CATEGORY) is None:
            ed = QtWidgets.QComboBox(table)
            ed.setEditable(True)
            ed.addItem("")
            for c in get_categories():
                ed.addItem(c)
            ed.lineEdit().setFrame(False)
            ed.setCurrentText(t["category"] or "")
            ed.setStyleSheet(badge_overlay_qss())
            ed._badge_focused_state = False
            # 默认鼠标穿透：悬浮零变化（胶囊仍由 delegate 画），仅单击才进编辑态
            ed.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            # 悬浮不吞字：NoFocus 使 hover 不会把键盘焦点交给 combo（鼠标穿透挡不住
            # QAbstractItemView 的 hover 聚焦），只有单击激活路径才临时恢复 StrongFocus。
            ed.setFocusPolicy(QtCore.Qt.NoFocus)
            ed.activated.connect(lambda _i, r=r: _on_category_committed(r))
            ed.lineEdit().returnPressed.connect(lambda r=r: _on_category_committed(r))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            # 双击事件实际投递到内嵌 line edit，必须同时装到它上面
            ed.lineEdit().installEventFilter(
                _DblClickFilter(r, _on_widget_dbl_click, ed.lineEdit()))
            _badge_filter = _BadgeStateFilter(ed)
            ed.installEventFilter(_badge_filter)
            if ed.lineEdit() is not None:
                ed.lineEdit().installEventFilter(_badge_filter)
            table.setCellWidget(r, COL_CATEGORY, ed)
        # 优先级
        if table.cellWidget(r, COL_PRIORITY) is None:
            ed = QtWidgets.QComboBox(table)
            for i in (0, 1, 2, 3):
                ed.addItem(PRIORITY_LABELS[i], i)
            ed.setCurrentIndex(ed.findData(t["priority"]))
            ed.setFrame(False)
            ed.setStyleSheet(badge_overlay_qss())
            ed._badge_focused_state = False
            ed.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            ed.setFocusPolicy(QtCore.Qt.NoFocus)
            ed.activated.connect(lambda _i, r=r: _on_priority_committed(r))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            _badge_filter = _BadgeStateFilter(ed)
            ed.installEventFilter(_badge_filter)
            if ed.lineEdit() is not None:
                ed.lineEdit().installEventFilter(_badge_filter)
            table.setCellWidget(r, COL_PRIORITY, ed)
        # 状态
        if table.cellWidget(r, COL_STATUS) is None:
            ed = QtWidgets.QComboBox(table)
            ed.setEditable(True)
            for s in get_statuses():
                ed.addItem(s["name"], s["id"])
            st = _status_map.get(t["status_id"])
            ed.setCurrentIndex(ed.findData(t["status_id"]))
            ed.lineEdit().setFrame(False)
            ed.setStyleSheet(badge_overlay_qss())
            ed._badge_focused_state = False
            ed.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            ed.setFocusPolicy(QtCore.Qt.NoFocus)
            ed.activated.connect(lambda _i, r=r: _on_status_committed(r))
            ed.lineEdit().returnPressed.connect(lambda r=r: _on_status_committed(r))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            ed.lineEdit().installEventFilter(
                _DblClickFilter(r, _on_widget_dbl_click, ed.lineEdit()))
            _badge_filter = _BadgeStateFilter(ed)
            ed.installEventFilter(_badge_filter)
            if ed.lineEdit() is not None:
                ed.lineEdit().installEventFilter(_badge_filter)
            table.setCellWidget(r, COL_STATUS, ed)
        # 截止日期：只读 + 日历选择（点击不再自动填入日期），右侧清除按钮可清回「无」
        if table.cellWidget(r, COL_DUE) is None:
            holder = QtWidgets.QWidget(table)
            hlay = QtWidgets.QHBoxLayout(holder)
            hlay.setContentsMargins(0, 0, 0, 0)
            hlay.setSpacing(0)
            ed = QtWidgets.QDateEdit(holder)
            # 整个控件设为 readOnly 会让日历弹不出来（实测点击无反应），
            # 因此只让内部 lineEdit 只读：不能手输，但点击日历箭头仍能弹出日历选择。
            ed.setReadOnly(False)
            ed.lineEdit().setReadOnly(True)
            ed.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("yyyy-MM-dd")
            ed.setSpecialValueText("无")
            ed.setMinimumDate(QtCore.QDate(1900, 1, 1))
            ed.blockSignals(True)
            if t["due_date"]:
                d = QtCore.QDate.fromString(t["due_date"], "yyyy-MM-dd")
                ed.setDate(d if d.isValid() else QtCore.QDate(1900, 1, 1))
            else:
                ed.setDate(QtCore.QDate(1900, 1, 1))
            ed.blockSignals(False)
            ed.setStyleSheet(editor_qss())
            ed.dateChanged.connect(lambda d, r=r: _on_due_changed(r, d))
            ed.installEventFilter(_DblClickFilter(r, _on_widget_dbl_click, ed))
            if ed.lineEdit() is not None:
                ed.lineEdit().installEventFilter(
                    _DblClickFilter(r, _on_widget_dbl_click, ed.lineEdit()))
            btn = QtWidgets.QToolButton(holder)
            btn.setObjectName("todo_due_clear")
            btn.setText("×")
            btn.setAutoRaise(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, r=r: _clear_due(r))
            # 清除键：默认隐藏不占位（日期控件 stretch=1 吃满宽度 → 视觉贴右），
            # 悬浮单元格才出现；尺寸走令牌，紧凑 QSS 覆盖全局 QToolButton 的 padding。
            btn.setFixedSize(_sz["todo_due_clear_size"], _sz["todo_due_clear_size"])
            btn.setStyleSheet("QToolButton { padding: 0; border: none; }")
            btn.setVisible(False)
            holder.installEventFilter(_DueHoverFilter(holder, btn))
            hlay.addWidget(ed, 1)
            hlay.addWidget(btn, 0)
            table.setCellWidget(r, COL_DUE, holder)

    def _visible_rows():
        """当前可见行集合（_sync_cell_widgets 与 _refresh_option_widgets 共用）。"""
        try:
            table.rowCount()
        except RuntimeError:
            return set()
        vp = table.viewport()
        first = table.rowAt(0)
        last = table.rowAt(vp.height() - 1)
        if first < 0:
            first = 0
        if last < 0:
            last = table.rowCount() - 1
        return set(range(first, last + 1))

    def _sync_cell_widgets():
        """为可见行创建常驻编辑器，销毁不可见行的编辑器（防泄漏）。"""
        try:
            table.rowCount()
        except RuntimeError:
            return
        visible = _visible_rows()
        for r in range(table.rowCount()):
            if r in visible:
                continue
            for c in _WIDGET_COLS:
                w = table.cellWidget(r, c)
                if w is not None:
                    table.removeCellWidget(r, c)
                    w.deleteLater()
        for r in visible:
            if r < len(_all_todos):
                _ensure_row_widgets(r)

    def _refresh_option_widgets():
        """就地刷新可见行选项下拉（类别/状态），保留各行当前值。

        手输新类别/标签管理增删后调用：不清空用户已选/已输入的值，
        只重填选项列表，让其它行与工具栏筛选立即看到新类别。
        """
        categories = get_categories()
        statuses = get_statuses()
        for r in _visible_rows():
            if r >= len(_all_todos):
                continue
            ed = table.cellWidget(r, COL_CATEGORY)
            if ed is not None:
                current = ed.currentText()
                ed.blockSignals(True)
                ed.clear()
                ed.addItem("")
                for c in categories:
                    ed.addItem(c)
                ed.setCurrentText(current)
                ed.blockSignals(False)
            ed = table.cellWidget(r, COL_STATUS)
            if ed is not None:
                current_id = ed.currentData()
                ed.blockSignals(True)
                ed.clear()
                for s in statuses:
                    ed.addItem(s["name"], s["id"])
                idx = ed.findData(current_id)
                ed.setCurrentIndex(idx if idx >= 0 else 0)
                ed.blockSignals(False)

    def _destroy_cell_widgets():
        """销毁全部常驻编辑器（refresh 重建前调用）。"""
        try:
            table.rowCount()
        except RuntimeError:
            return
        for r in range(table.rowCount()):
            for c in _WIDGET_COLS:
                w = table.cellWidget(r, c)
                if w is not None:
                    table.removeCellWidget(r, c)
                    w.deleteLater()

    class _ViewportResizeFilter(QtCore.QObject):
        """视口尺寸变化时重同步常驻编辑器。

        refresh() 时表格尚未布局，只会为当时“可见”的少数行建控件；窗口放大后
        新暴露的行必须补建，否则同表会混排“编辑器行”与“delegate 徽章行”。
        用 _pending 合并同一轮布局中的多次 Resize。
        """

        def __init__(self, parent):
            super().__init__(parent)
            self._pending = False

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Resize and not self._pending:
                self._pending = True
                QtCore.QTimer.singleShot(0, self._flush)
            return False

        def _flush(self):
            self._pending = False
            try:
                _fit_content_heights()   # 列宽变化会改行高，进而改变可见行集
                _sync_cell_widgets()
            except RuntimeError:
                pass

    _resize_filter = _ViewportResizeFilter(table.viewport())
    table.viewport().installEventFilter(_resize_filter)

    class _RowDblClickFilter(QtCore.QObject):
        """表格视口双击：行内任意位置都打开详情页。

        单元格被常驻编辑器覆盖时，事件由控件自己的 _DblClickFilter 处理；
        此处兜底未被覆盖的区域（勾选列、创建时间列、单元格内边距），
        避免「有的地方能双击进详情页、有的地方不能」。
        """

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.MouseButtonDblClick:
                try:
                    y = int(event.position().y())
                except AttributeError:
                    y = int(event.pos().y())
                row = table.rowAt(y)
                if row >= 0:
                    _on_widget_dbl_click(row)
                    return True
            return False

    _row_dbl_filter = _RowDblClickFilter(table.viewport())
    table.viewport().installEventFilter(_row_dbl_filter)

    def _activate_badge_editor(ed, row, col):
        """延迟激活选项列编辑器：解除穿透、聚焦、弹下拉。

        延迟到 press/release 周期结束后执行：同步执行会让紧随的
        MouseButtonRelease 落在弹窗外而立刻关闭弹窗，且视口的 press 处理会把
        焦点抢回表格。控件已被 _sync_cell_widgets 回收时安全跳过。
        """
        try:
            if table.cellWidget(row, col) is not ed:
                return
            # 单击激活路径：先恢复可聚焦（NoFocus 会挡住 setFocus），再解除穿透。
            ed.setFocusPolicy(QtCore.Qt.StrongFocus)
            ed.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
            ed.setFocus()
            ed.showPopup()
        except RuntimeError:
            pass

    class _CellClickFilter(QtCore.QObject):
        """选项列单元格单击：把命中格的常驻 combo 转入编辑态。

        选项列 combo 默认 WA_TransparentForMouseEvents（悬浮零变化，胶囊由
        delegate 绘制）；单击落在视口上时，延迟到 press/release 结束后解除该格
        穿透、聚焦并弹出下拉（类别/状态仍可手输）。不消费事件，行选择等表格
        行为照常进行。
        """

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.MouseButtonPress \
                    and event.button() == QtCore.Qt.LeftButton:
                try:
                    pos = event.position()
                    x, y = int(pos.x()), int(pos.y())
                except AttributeError:
                    x, y = int(event.pos().x()), int(event.pos().y())
                row = table.rowAt(y)
                col = table.columnAt(x)
                if row >= 0 and col in _BADGE_COLS:
                    ed = table.cellWidget(row, col)
                    if ed is not None:
                        QtCore.QTimer.singleShot(
                            0, lambda ed=ed, row=row, col=col:
                            _activate_badge_editor(ed, row, col))
            return False

    _cell_click_filter = _CellClickFilter(table.viewport())
    table.viewport().installEventFilter(_cell_click_filter)

    def _on_cell_double_clicked(row, col):
        on_edit()

    table.cellDoubleClicked.connect(_on_cell_double_clicked)

    refresh_categories()
    refresh()
    # 内容列宽变化（自适应 reflow 首次落定、窗口缩放、用户拖拽）时按最新列宽重算行高，
    # 避免首次打开时所有行都按窄列宽折行成 6 行，点击后才自适应到实际行数。
    # 行高变化会改变可见行集，故常驻编辑器需一并重同步。
    def _on_section_resized(logical, *_a):
        if logical == COL_CONTENT:
            _fit_content_heights()
            _sync_cell_widgets()

    table.horizontalHeader().sectionResized.connect(_on_section_resized)
    # 透明表格滚动多行内容时，Qt 的部分重绘可能残留旧文字描边/轮廓；
    # 滚动即整块刷新视口，即时清除残留、避免“文字的描边还在”。
    table.verticalScrollBar().valueChanged.connect(lambda *_: table.viewport().update())
    table.verticalScrollBar().valueChanged.connect(lambda *_: _sync_cell_widgets())
    table.horizontalScrollBar().valueChanged.connect(lambda *_: table.viewport().update())
    owner._page_refresh = lambda: (refresh_categories(), refresh())
    return w
