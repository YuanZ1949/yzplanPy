"""todo_notes 页面辅助：_page_context_menu/_maybe_reset_done_on_content_change/_TodoEditDialog。

[_build_todo_menu / _pick_cell_color_for: todo 16 右键改色]
"""
from datetime import datetime
import math
from sqlite3 import IntegrityError
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import sizing, theme_palette
from ui.widgets import make_button, make_combo, make_line_edit, make_label
from ..todo_store import (delete_category, delete_status, delete_todo,
                          get_categories, get_or_create_status, get_statuses,
                          get_option_color, rename_category, rename_status,
                          set_option_color, set_status_color, update_todo)
from .constants import (COL_CATEGORY, COL_PRIORITY, COL_STATUS,
                        COLOR_COL_CATEGORY, COLOR_COL_PRIORITY,
                        CONTENT_FIT_SLACK, CUSTOM_OPTION_DATA,
                        CUSTOM_OPTION_LABEL, category_color, priority_color,
                        status_color, wrapped_line_count)
from .date_theme import _apply_date_theme


def _build_todo_menu(todo, col, color_row):
    """构建便签右键菜单；选项列（状态/类别）附带「设置颜色/重命名/删除」入口。

    Returns:
        (menu, actions_dict): actions_dict keys —
            toggle/copy/edit/high/hi/mid/low/del/color/rename_opt/delete_opt
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
    act_rename_opt = None
    act_delete_opt = None
    if col in (COL_STATUS, COL_PRIORITY, COL_CATEGORY) and color_row >= 0:
        menu.addSeparator()
        act_color = menu.addAction("设置颜色...")
    if col in (COL_STATUS, COL_CATEGORY) and color_row >= 0:
        menu.addSeparator()
        act_rename_opt = menu.addAction("重命名")
        act_delete_opt = menu.addAction("删除该选项")
    return menu, {
        "toggle": act_toggle, "copy": act_copy, "edit": act_edit,
        "high": act_high, "hi": act_hi, "mid": act_mid, "low": act_low,
        "del": act_del, "color": act_color, "rename_opt": act_rename_opt,
        "delete_opt": act_delete_opt,
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


def _rename_cell_option(table, row, col, refresh):
    """右键重命名状态/类别选项：QInputDialog 输入新名 → rename_status/rename_category → 刷新。"""
    item = table.item(row, col)
    if item is None:
        return
    old = (item.text() or "").strip()
    if not old:
        return
    new, ok = QtWidgets.QInputDialog.getText(
        table.window(), "重命名", "新名称：", text=old)
    if not ok:
        return
    new = (new or "").strip()
    if not new or new == old:
        return
    try:
        if col == COL_STATUS:
            rename_status(item.data(QtCore.Qt.UserRole), new)
        else:
            rename_category(old, new)
    except (ValueError, IntegrityError):
        return
    refresh()


def _delete_cell_option(table, row, col, refresh):
    """右键删除状态/类别选项：确认后 delete_status/delete_category → 刷新（「待办」不可删）。"""
    item = table.item(row, col)
    if item is None:
        return
    name = (item.text() or "").strip()
    if not name:
        return
    ret = QtWidgets.QMessageBox.question(
        table.window(), "删除该选项", f"确定删除「{name}」？",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.No)
    if ret != QtWidgets.QMessageBox.Yes:
        return
    try:
        if col == COL_STATUS:
            delete_status(item.data(QtCore.Qt.UserRole))
        else:
            delete_category(name)
    except (ValueError, IntegrityError):
        return
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
    elif action == acts["rename_opt"]:
        _rename_cell_option(table, row_at, col_at, refresh)
    elif action == acts["delete_opt"]:
        _delete_cell_option(table, row_at, col_at, refresh)


def _maybe_reset_done_on_content_change(todo_id, old_content, new_content):
    """内容字段变化时同步 done/status：清空视为完成，修改视为回到「待办」。

    - 内容被清空 → 自动标记为已完成（done=1，status_id=「已完成」）。
    - 内容被修改（非清空）→ 可能有新增事项，重置为「待办」（done=0）。
    done 与 status_id 同步：todo 2 后状态列渲染由 status_id 驱动，
    仅置 done 会让状态列仍显示旧状态（用户报告"没看到生效"）。
    """
    if old_content != new_content:
        if new_content == "":
            update_todo(todo_id, done=1, status_id=get_or_create_status("已完成"))
        else:
            update_todo(todo_id, done=0, status_id=get_or_create_status("待办"))


class _ShowRefitFilter(QtCore.QObject):
    """对话框首次显示后重算内容框高度。

    QPlainTextEdit 的文档在显示前未按最终宽度布局，doc.size().height() 此时
    只返回段落数（漏算自动折行），单段长文本会算出偏矮的内容框 → 内部滚动条、
    末行文字被截断。Show 之后布局完成，重算一次即可贴合内容。
    """

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Show:
            self._callback()
        return False


class _TodoEditDialog:
    """便签编辑/新增对话框：支持全部属性（标题/内容/类别/优先级/截止/状态/颜色）。

    状态为可编辑下拉（选项来自 get_statuses()，输入新名即"改名即新建"）；
    颜色为状态色块（与 todo 16 标签管理一致的画板入口，QColorDialog 持久化）。
    """

    def __init__(self, parent=None, todo=None):
        self._todo = todo
        self._dlg = QtWidgets.QDialog(parent)
        self._dlg.setWindowTitle("编辑待办" if todo else "新增待办")
        sz = sizing()
        self._dlg.setMinimumSize(420, 380)

        lay = QtWidgets.QVBoxLayout(self._dlg)
        lay.setContentsMargins(sz["dialog_margin"], sz["dialog_margin"],
                               sz["dialog_margin"], sz["dialog_margin"])
        lay.setSpacing(sz["dialog_spacing"])

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(sz["dialog_spacing"])
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # 标题
        self.title_input = make_line_edit("", parent=self._dlg)
        self.title_input.setText(todo["title"] if todo else "")
        form.addRow(make_label("标题", role="body"), self.title_input)

        # 内容（多行，按文档高度自适应：不留固定空行，超上限才内部滚动）
        self.content_input = QtWidgets.QPlainTextEdit(self._dlg)
        # 水平滚动条恒关（内容始终折行）：一旦出现会吃掉视口高度 14px，
        # 与垂直滚动条形成「高度不足 → vbar → 宽度变窄 → 折行变多 → hbar」死循环。
        self.content_input.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content_input.setPlainText(todo["content"] if todo else "")
        form.addRow(make_label("内容", role="body"), self.content_input)

        # 类别（可编辑下拉 + 「自定义…」哨兵 + 颜色色块）
        cat_row = QtWidgets.QHBoxLayout()
        cat_row.setSpacing(sz["dialog_spacing"])
        self.cat_combo = make_combo(parent=self._dlg)
        self.cat_combo.setEditable(True)
        self.cat_combo.addItem("（无类别）", userData="")
        for c in get_categories():
            self.cat_combo.addItem(c, userData=c)
        self.cat_combo.addItem(CUSTOM_OPTION_LABEL, userData=CUSTOM_OPTION_DATA)
        self.cat_combo.setPlaceholderText("选择或输入新类别")
        if todo and todo.get("category"):
            idx = self.cat_combo.findData(todo["category"])
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)
            else:
                self.cat_combo.setCurrentText(todo["category"])
        cat_row.addWidget(self.cat_combo, 1)
        self.cat_color_btn = self._make_swatch(self._current_category_swatch())
        self.cat_color_btn.clicked.connect(self._pick_category_swatch)
        cat_row.addWidget(self.cat_color_btn)
        cat_row.addStretch(0)
        form.addRow(make_label("类别", role="body"), cat_row)

        # 优先级（与类别/状态行同构：尾部占位与色块等宽，保证三个下拉框等宽）
        pri_row = QtWidgets.QHBoxLayout()
        pri_row.setSpacing(sz["dialog_spacing"])
        self.pri_combo = make_combo(parent=self._dlg)
        for label, val in (("低", 0), ("中", 1), ("高", 2), ("紧急", 3)):
            self.pri_combo.addItem(label, userData=val)
        if todo:
            idx = self.pri_combo.findData(todo["priority"])
            if idx >= 0:
                self.pri_combo.setCurrentIndex(idx)
        pri_row.addWidget(self.pri_combo, 1)
        pri_spacer = QtWidgets.QWidget(self._dlg)
        pri_spacer.setFixedWidth(sz["btn_height_sm"])
        pri_row.addWidget(pri_spacer)
        pri_row.addStretch(0)
        form.addRow(make_label("优先级", role="body"), pri_row)

        # 截止日期
        due_row = QtWidgets.QHBoxLayout()
        due_row.setSpacing(sz["dialog_spacing"])
        self.due_check = QtWidgets.QCheckBox("启用", self._dlg)
        due_row.addWidget(self.due_check)
        self.due_date = QtWidgets.QDateEdit(self._dlg)
        self.due_date.setCalendarPopup(True)
        _apply_date_theme(self.due_date)
        self.due_date.setDate(QtCore.QDate.currentDate())
        self.due_date.setEnabled(False)
        due_row.addWidget(self.due_date)
        due_row.addStretch(1)
        if todo and todo["due_date"]:
            self.due_check.setChecked(True)
            self.due_date.setEnabled(True)
            try:
                d = datetime.strptime(todo["due_date"], "%Y-%m-%d")
                self.due_date.setDate(QtCore.QDate(d.year, d.month, d.day))
            except ValueError:
                pass
        self.due_check.toggled.connect(self.due_date.setEnabled)
        form.addRow(make_label("截止日期", role="body"), due_row)

        # 状态（可编辑下拉，改名即新建）+ 颜色色块
        status_row = QtWidgets.QHBoxLayout()
        status_row.setSpacing(sz["dialog_spacing"])
        self.status_combo = make_combo(parent=self._dlg)
        self.status_combo.setEditable(True)
        for s in get_statuses():
            self.status_combo.addItem(s["name"], userData=s["id"])
        self.status_combo.addItem(CUSTOM_OPTION_LABEL, userData=CUSTOM_OPTION_DATA)
        if todo:
            idx = self.status_combo.findData(todo["status_id"])
            if idx >= 0:
                self.status_combo.setCurrentIndex(idx)
        status_row.addWidget(self.status_combo, 1)
        self.color_btn = self._make_swatch(self._current_status_swatch())
        self.color_btn.clicked.connect(self._pick_swatch)
        status_row.addWidget(self.color_btn)
        status_row.addStretch(0)
        form.addRow(make_label("状态", role="body"), status_row)

        # 完成勾选（覆盖表格「勾选」列；与状态下拉双向同步）
        self.done_check = QtWidgets.QCheckBox("已完成", self._dlg)
        if todo:
            self.done_check.setChecked(bool(todo.get("done")))
        form.addRow(make_label("完成", role="body"), self.done_check)

        # 创建时间（覆盖表格「创建时间」列，可编辑）
        self.created_at_edit = QtWidgets.QDateTimeEdit(self._dlg)
        self.created_at_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.created_at_edit.setCalendarPopup(True)
        if todo and todo.get("created_at"):
            try:
                cdt = datetime.strptime(todo["created_at"][:16], "%Y-%m-%d %H:%M")
                self.created_at_edit.setDateTime(
                    QtCore.QDateTime(cdt.year, cdt.month, cdt.day, cdt.hour, cdt.minute, 0))
            except ValueError:
                pass
        form.addRow(make_label("创建时间", role="body"), self.created_at_edit)

        lay.addLayout(form)

        # 按钮行
        btn_row = QtWidgets.QHBoxLayout()
        btn_manage = make_button("标签管理…", size="sm", parent=self._dlg)
        btn_manage.clicked.connect(self._open_tag_manager)
        btn_row.addWidget(btn_manage)
        btn_row.addStretch(1)
        btn_cancel = make_button("取消", parent=self._dlg)
        btn_cancel.clicked.connect(self._dlg.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = make_button("确定", kind="primary", parent=self._dlg)
        btn_ok.clicked.connect(self._dlg.accept)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

        # 状态变化时同步色块颜色
        self.status_combo.currentIndexChanged.connect(self._sync_swatch)
        self.status_combo.lineEdit().textChanged.connect(self._sync_swatch)
        # 完成勾选 ↔ 状态 双向同步（is_done_like 为唯一真相源，不会自激）
        self.status_combo.currentIndexChanged.connect(self._sync_done_from_status)
        self.done_check.toggled.connect(self._sync_status_from_done)
        # 「自定义…」哨兵：选中即进入行内编辑（清空 + 聚焦）
        self.status_combo.currentIndexChanged.connect(
            lambda *_: self._on_option_combo_index_changed(self.status_combo))
        self.cat_combo.currentIndexChanged.connect(
            lambda *_: self._on_option_combo_index_changed(self.cat_combo))
        self.cat_combo.lineEdit().textChanged.connect(self._sync_cat_swatch)
        # 内容框按文档高度自适应（打开即显示全部内容，不留固定空行）
        self.content_input.textChanged.connect(self._fit_content_height)
        self._fit_content_height()
        # 显示前文档未按最终宽度布局，show 后按真实宽度重算一次（见 _ShowRefitFilter）
        self._show_refit = _ShowRefitFilter(self._fit_content_height)
        self._dlg.installEventFilter(self._show_refit)

    # -- 内容高度自适应 ----------------------------------------------

    def _fit_content_height(self):
        """内容框贴合文档：完整显示内容、不预留空行；超上限才内部滚动。

        行数优先按真实 viewport 宽显式折算（wrapped_line_count）：文档显示前
        未按最终宽度布局，doc.size().height() 只报段落数、漏算自动折行，单段
        长文本会算出偏矮的内容框（内部滚动条 + 末行截断）。未显示时退化为
        段落数作初始估算，显示后由 _ShowRefitFilter 重算。
        公式含 2×frameWidth（上下边框）：真实 Windows QPA 下 QPlainTextEdit
        frame=2px，漏计会矮 1-2px 导致内容框出现内部滚动条。
        末尾再加 CONTENT_FIT_SLACK：Qt 文档像素高按浮点行距向上取整，恰好贴边时
        会差 1px 而触发内部滚动条。
        """
        ci = self.content_input
        ci.ensurePolished()  # 主题 QSS 的 QPlainTextEdit padding 在 polish 后才生效：先 polish 再量 chrome
        doc = ci.document()
        doc.setDocumentMargin(sizing()["todo_editor_doc_margin"])
        fm = QtGui.QFontMetrics(ci.font())
        margins = ci.contentsMargins()
        # 折行宽度按「不含滚动条的全内宽」计算：viewport().width() 会被垂直滚动条
        # 占去约 14px，导致折行数偏多、内容框偏高（hbar/vbar 死循环的另一半）。
        inner_w = (ci.width() - 2 * ci.frameWidth()
                   - margins.left() - margins.right())
        avail_w = inner_w - 2 * doc.documentMargin()
        if ci.isVisible() and avail_w > 10:
            lines = wrapped_line_count(ci.toPlainText(), ci.font(), avail_w)
        else:
            lines = doc.size().height()
        text_h = lines * fm.lineSpacing()
        chrome = margins.top() + margins.bottom() + 2 * doc.documentMargin() + 2 * ci.frameWidth()
        cap = sizing()["todo_dialog_content_max_height"]
        single = math.ceil(fm.lineSpacing() + chrome)
        ci.setFixedHeight(min(math.ceil(text_h + chrome) + CONTENT_FIT_SLACK, cap))
        # 弹窗随内容框长高：显式激活布局后按 sizeHint 定高（隐藏期 adjustSize
        # 无效，resize 尊重 setMinimumSize(420, 380) 下限，不会缩破最小尺寸）
        self._dlg.layout().activate()
        self._dlg.resize(self._dlg.layout().totalSizeHint())
        # 超屏兜底：弹窗仍高于屏幕可用高度时压缩内容框（不低于单行高）
        avail_h = self._dlg.screen().availableGeometry().height()
        if self._dlg.height() > avail_h:
            ci.setFixedHeight(max(ci.height() - (self._dlg.height() - avail_h), single))
            self._dlg.layout().activate()
            self._dlg.resize(self._dlg.layout().totalSizeHint())

    # -- 状态/颜色 ----------------------------------------------------

    def _status_id_by_done(self, done):
        """按 is_done_like 取一个状态 id（优先「已完成」/「待办」）。"""
        statuses = get_statuses()
        preferred = "已完成" if done else "待办"
        for s in statuses:
            if bool(s["is_done_like"]) == bool(done) and s["name"] == preferred:
                return s["id"]
        for s in statuses:
            if bool(s["is_done_like"]) == bool(done):
                return s["id"]
        return None

    def _sync_done_from_status(self, *_):
        st = self._current_status()
        if st is not None:
            self.done_check.setChecked(bool(st["is_done_like"]))

    def _sync_status_from_done(self, checked):
        sid = self._status_id_by_done(checked)
        if sid is None:
            return
        idx = self.status_combo.findData(sid)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)

    def _current_status(self):
        """当前状态下拉选中的 status dict（新输入名返回 None）。"""
        text = (self.status_combo.currentText() or "").strip()
        if not text:
            return None
        for s in get_statuses():
            if s["name"] == text:
                return s
        return None

    def _current_status_swatch(self):
        st = self._current_status()
        return status_color(st) if st else theme_palette()["todo_editor_border"]

    def _make_swatch(self, color):
        p = theme_palette()
        sz = sizing()
        btn = make_button("", size="sm", parent=self._dlg)
        btn.setFixedWidth(btn.height())
        btn.setStyleSheet(
            f"QPushButton {{ background: {color};"
            f" border: 1px solid {p['border']};"
            f" border-radius: {sz['radius_sm']}px; }}"
        )
        btn._swatch_color = color  # type: ignore[attr-defined]
        return btn

    def _apply_swatch(self, color, btn=None):
        p = theme_palette()
        sz = sizing()
        btn = btn or self.color_btn
        btn.setStyleSheet(
            f"QPushButton {{ background: {color};"
            f" border: 1px solid {p['border']};"
            f" border-radius: {sz['radius_sm']}px; }}"
        )
        btn._swatch_color = color  # type: ignore[attr-defined]

    def _sync_swatch(self, *_):
        self._apply_swatch(self._current_status_swatch())

    def _pick_swatch(self):
        """点击色块：QColorDialog 选色 → 持久化到当前状态（改名即新建）。"""
        st = self._current_status()
        if st is None:
            # 新状态名：先创建（改名即新建语义），再设色
            name = (self.status_combo.currentText() or "").strip()
            if not name:
                return
            sid = get_or_create_status(name)
            st = {"id": sid, "name": name, "color": None}
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.color_btn._swatch_color), self._dlg, "设置颜色")  # type: ignore[attr-defined]
        if not color.isValid():
            return
        hex_color = color.name()
        set_status_color(st["id"], hex_color)
        self._apply_swatch(hex_color)

    def _current_category(self):
        """当前类别下拉选中的类别名（新输入名/哨兵返回 None）。"""
        text = (self.cat_combo.currentText() or "").strip()
        if not text or text == CUSTOM_OPTION_LABEL:
            return None
        return text

    def _current_category_swatch(self):
        cat = self._current_category()
        return category_color(cat) if cat else theme_palette()["todo_editor_border"]

    def _sync_cat_swatch(self, *_):
        self._apply_swatch(self._current_category_swatch(), self.cat_color_btn)

    def _pick_category_swatch(self):
        """点击类别色块：QColorDialog 选色 → set_option_color 持久化。"""
        cat = self._current_category()
        if cat is None:
            return
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.cat_color_btn._swatch_color), self._dlg, "设置颜色")  # type: ignore[attr-defined]
        if not color.isValid():
            return
        set_option_color(COLOR_COL_CATEGORY, cat, color.name())
        self._apply_swatch(color.name(), self.cat_color_btn)

    def _on_option_combo_index_changed(self, combo):
        """下拉选中「自定义…」哨兵：清空输入并聚焦行内编辑（居中样式）。"""
        idx = combo.currentIndex()
        if idx < 0:
            return
        if combo.itemData(idx) == CUSTOM_OPTION_DATA:
            if not getattr(combo, "_custom_entered", False):
                combo._custom_entered = True  # type: ignore[attr-defined]
                combo.setCurrentText("")
                le = combo.lineEdit()
                if le is not None:
                    try:
                        le.setAlignment(QtCore.Qt.AlignCenter)
                        le.setFocus()
                    except RuntimeError:
                        pass
        else:
            combo._custom_entered = False  # type: ignore[attr-defined]
            le = combo.lineEdit()
            if le is not None:
                try:
                    le.setAlignment(QtCore.Qt.AlignLeft)
                except RuntimeError:
                    pass

    def _open_tag_manager(self):
        """打开标签管理窗口；关闭后按数据库现状重建两个下拉（避免 ghost 复活）。"""
        from .tag_manager import _TagManagerDialog
        _TagManagerDialog(self._dlg).exec()
        self._reload_option_combos()

    def _reload_option_combos(self):
        """标签管理改动后重建状态/类别下拉：编辑态还原为该条当前值，新增态清空。"""
        todo = self._todo
        statuses = get_statuses()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        for s in statuses:
            self.status_combo.addItem(s["name"], userData=s["id"])
        self.status_combo.addItem(CUSTOM_OPTION_LABEL, userData=CUSTOM_OPTION_DATA)
        sid = (todo or {}).get("status_id")
        idx = self.status_combo.findData(sid) if sid is not None else -1
        self.status_combo.setCurrentIndex(idx if idx >= 0 else (0 if statuses else -1))
        self.status_combo.blockSignals(False)

        categories = get_categories()
        cur_cat = (todo or {}).get("category") or ""
        self.cat_combo.blockSignals(True)
        self.cat_combo.clear()
        self.cat_combo.addItem("（无类别）", userData="")
        for c in categories:
            self.cat_combo.addItem(c, userData=c)
        self.cat_combo.addItem(CUSTOM_OPTION_LABEL, userData=CUSTOM_OPTION_DATA)
        self.cat_combo.setCurrentText(cur_cat if cur_cat in categories else "")
        self.cat_combo.blockSignals(False)
        self._sync_swatch()
        self._sync_cat_swatch()
        self._sync_done_from_status()

    def exec(self):
        return self._dlg.exec()

    def get_data(self):
        due = None
        if self.due_check.isChecked():
            d = self.due_date.date()
            due = f"{d.year()}-{d.month():02d}-{d.day():02d}"
        category = (self.cat_combo.currentText() or "").strip()
        if category == CUSTOM_OPTION_LABEL:
            category = (self._todo or {}).get("category") or ""
        data = {
            "title": self.title_input.text().strip(),
            "content": self.content_input.toPlainText().strip(),
            "priority": self.pri_combo.currentData(),
            "category": category,
            "due_date": due,
        }
        status_text = (self.status_combo.currentText() or "").strip()
        if status_text == CUSTOM_OPTION_LABEL:
            status_text = ""
        if status_text:
            data["status_id"] = get_or_create_status(status_text)
        elif self._todo:
            data["status_id"] = self._todo.get("status_id")
        data["done"] = 1 if self.done_check.isChecked() else 0
        data["created_at"] = self.created_at_edit.dateTime().toString(
            "yyyy-MM-dd HH:mm") + ":00"
        return data
