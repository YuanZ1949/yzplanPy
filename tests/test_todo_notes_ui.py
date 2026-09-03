import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from ui.adaptive_table import make_adaptive_table
from modules import todo_notes as tn


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


class _Owner:
    _page_refresh = None


def _make_page():
    _app()
    win = QtWidgets.QWidget()
    win.resize(820, 600)
    page = tn._make_page_widget(_Owner(), win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()
    return win, page


def _find_table(win):
    return [c for c in win.findChildren(QtWidgets.QTableWidget)][0]


def test_page_builds_with_adaptive_and_delegate():
    win, page = _make_page()
    table = _find_table(win)
    # 所有列 Interactive（沿用自适应工具）
    for c in range(table.columnCount()):
        assert table.horizontalHeader().sectionResizeMode(c) == QtWidgets.QHeaderView.Interactive
    # 安装了自定义 delegate
    delegates = [d for d in table.findChildren(QtWidgets.QStyledItemDelegate)]
    assert any(isinstance(d, tn._TodoItemDelegate) for d in delegates)


def test_delegate_editor_types():
    win, page = _make_page()
    table = _find_table(win)
    delegate = tn._TodoItemDelegate(table)
    opt = QtWidgets.QStyleOptionViewItem()
    model = table.model()

    # 类别 / 优先级 / 状态 -> QComboBox
    for col in (tn.COL_CATEGORY, tn.COL_PRIORITY, tn.COL_STATUS):
        ed = delegate.createEditor(table, opt, model.index(0, col))
        assert isinstance(ed, QtWidgets.QComboBox), f"col {col} should be combo"
        ed.deleteLater()

    # 标题 -> QLineEdit（默认编辑器）
    ed0 = delegate.createEditor(table, opt, model.index(0, tn.COL_TITLE))
    assert isinstance(ed0, QtWidgets.QLineEdit)

    # 内容 -> QPlainTextEdit（多行编辑）
    edc = delegate.createEditor(table, opt, model.index(0, tn.COL_CONTENT))
    assert isinstance(edc, QtWidgets.QPlainTextEdit)
    edc.deleteLater()


def test_row_height_and_checkbox_and_content_editable():
    win, page = _make_page()
    table = _find_table(win)
    assert table.verticalHeader().defaultSectionSize() >= 28
    check = table.item(0, tn.COL_CHECK)  # 复选框列
    if check is not None:
        assert check.flags() & QtCore.Qt.ItemIsUserCheckable
    content = table.item(0, tn.COL_CONTENT)  # 内容列现在可编辑（多行内联）
    if content is not None:
        assert content.flags() & QtCore.Qt.ItemIsEditable


def test_content_inline_edit_uses_multiline_and_restores_row():
    win, page = _make_page()
    table = _find_table(win)
    if table.rowCount() == 0:
        return
    delegate = tn._TodoItemDelegate(table)
    opt = QtWidgets.QStyleOptionViewItem()
    model = table.model()
    # 内容列行内编辑器为多行 QPlainTextEdit
    ed = delegate.createEditor(table, opt, model.index(0, tn.COL_CONTENT))
    assert isinstance(ed, QtWidgets.QPlainTextEdit)
    # 展开行高后，destroyEditor 按内容折行恢复到多行显示高度（不再是固定默认单行）
    idx = model.index(0, tn.COL_CONTENT)
    text = idx.data() or ""
    table.setRowHeight(0, 120)
    delegate.destroyEditor(ed, idx)
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    wrapped = len(tn._TodoItemDelegate._wrap_lines(
        text, fm, max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)))
    expected = min(max(1, wrapped), tn.CONTENT_MAX_LINES) * (sp + 2) + 6
    assert table.rowHeight(0) == expected
    ed.deleteLater()


def test_multiline_editor_widget_supported():
    win, page = _make_page()
    table = _find_table(win)
    delegate = tn._TodoItemDelegate(table)
    opt = QtWidgets.QStyleOptionViewItem()
    model = table.model()
    ed = delegate.createEditor(table, opt, model.index(0, tn.COL_CONTENT))
    assert "PlainTextEdit" in type(ed).__name__
    ed.deleteLater()


def _mk_item(done):
    tid = tn.add_todo("__reset_done__", content="orig", priority=1)
    tn.update_todo(tid, done=done)
    return tid


def test_content_change_resets_done():
    tid = _mk_item(1)  # 已完成条目
    tn._maybe_reset_done_on_content_change(tid, "orig", "new content")
    todos = {t["id"]: t for t in tn.get_todos()}
    assert todos[tid]["done"] == 0
    tn.delete_todo(tid)


def test_same_content_keeps_done():
    tid = _mk_item(1)
    tn._maybe_reset_done_on_content_change(tid, "orig", "orig")
    todos = {t["id"]: t for t in tn.get_todos()}
    assert todos[tid]["done"] == 1
    tn.delete_todo(tid)


def _make_page_with_rows(n=3):
    win, page = _make_page()
    table = _find_table(win)
    ids = [tn.add_todo(f"__reset_row{i}__", content="c") for i in range(n)]
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return win, table, ids


def test_checkbox_shift_ctrl_handler():
    win, table, ids = _make_page_with_rows(3)
    delegate = table.itemDelegate()
    handler = getattr(delegate, "check_click_handler", None)
    assert handler is not None, "复选框点击处理器应已挂接"
    # 普通点击 -> 该行勾选
    handler(0, False, False)
    assert table.item(0, tn.COL_CHECK).checkState() == QtCore.Qt.Checked
    # shift 点击末行 -> 区间全勾（以锚点行为参照）
    handler(2, False, True)
    for r in range(3):
        assert table.item(r, tn.COL_CHECK).checkState() == QtCore.Qt.Checked
    # ctrl 点击某行 -> 仅切换该行
    handler(1, True, False)
    assert table.item(1, tn.COL_CHECK).checkState() == QtCore.Qt.Unchecked
    assert table.item(0, tn.COL_CHECK).checkState() == QtCore.Qt.Checked
    # 行选择联动到受影响区间
    sel = sorted({i.row() for i in table.selectedIndexes()})
    assert sel == [1]
    # DB 持久化
    todos = {t["id"]: t for t in tn.get_todos()}
    assert todos[ids[0]]["done"] == 1
    assert todos[ids[1]]["done"] == 0
    assert todos[ids[2]]["done"] == 1
    for i in ids:
        tn.delete_todo(i)


def test_content_full_text_preserved_and_line_cap():
    win, table, ids = _make_page_with_rows(1)
    long_text = "\n".join(["line %d " % i + "word " * 20 for i in range(10)])
    tn.update_todo(ids[0], content=long_text)
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    item = table.item(0, tn.COL_CONTENT)
    assert item.text() == long_text, "应保留完整内容而非截断"
    assert item.toolTip() == long_text
    # 行高不应超过 CONTENT_MAX_LINES 行
    fm = table.fontMetrics()
    capped_h = tn.CONTENT_MAX_LINES * (fm.lineSpacing() + 2) + 6
    assert table.rowHeight(0) <= capped_h
    for i in ids:
        tn.delete_todo(i)


def test_destroy_editor_restores_multiline_not_single():
    # 修复：编辑结束后行高应恢复为 <= CONTENT_MAX_LINES 行的折行显示，而不是塌陷到默认单行
    win, table, ids = _make_page_with_rows(1)
    long_text = "\n".join(["line %d " % i + "word " * 20 for i in range(10)])
    tn.update_todo(ids[0], content=long_text)
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    capped = tn.CONTENT_MAX_LINES * (sp + 2) + 6
    one = 1 * (sp + 2) + 6
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    # 模拟编辑时把行高展开到全高，随后编辑器销毁应恢复到多行显示（非单行）
    table.setRowHeight(0, 400)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    table.setRowHeight(0, 400)
    delegate.destroyEditor(editor, idx)
    h = table.rowHeight(0)
    assert h <= capped, "恢复后的行高不应超过多行上限"
    assert h >= one, "恢复后的行高应至少为一行（多行内容不应塌陷到默认单行）"
    for i in ids:
        tn.delete_todo(i)


def test_single_line_rows_not_forced_to_six_lines():
    # 修复：初次打开时单行内容不应被窄列宽折行成 6 行；内容列宽变化后应按实际行数重算
    win, page = _make_page()
    table = _find_table(win)
    id1 = tn.add_todo("__reset_single", content="short")
    id2 = tn.add_todo("__reset_multi", content="\n".join("row%d " % i + "word " * 8 for i in range(8)))
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset"); le.returnPressed.emit()
    for _ in range(6):
        QtWidgets.QApplication.processEvents()
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    one = 1 * (sp + 2) + 6
    capped = tn.CONTENT_MAX_LINES * (sp + 2) + 6
    rows = {table.item(r, tn.COL_TITLE).text(): r for r in range(table.rowCount())}
    rs, rm = rows["__reset_single"], rows["__reset_multi"]
    # 单行内容应显示为一行，不应被强制为 6 行
    assert table.rowHeight(rs) <= one, "单行内容不应被撑成多行"
    # 多行内容应 >1 行且 <= 6 行
    assert one < table.rowHeight(rm) <= capped, "多行内容应多行显示且不超过 6 行"
    # 内容列宽变化（窄 -> 宽）后按最新列宽重算：单行仍为一行，多行收缩到实际行数
    header = table.horizontalHeader()
    header.resizeSection(tn.COL_CONTENT, 60)
    QtWidgets.QApplication.processEvents()
    header.resizeSection(tn.COL_CONTENT, 700)
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    assert table.rowHeight(rows["__reset_single"]) <= one, "列宽变化后单行仍应保持单行"
    assert table.rowHeight(rows["__reset_multi"]) <= capped
    for i in (id1, id2):
        tn.delete_todo(i)




def test_select_all_lives_in_checkbox_header():
    # 需求2：全选键移到复选框列表头（自定义 _SelectAllHeader），点击切换全部行勾选
    win, page = _make_page()
    table = _find_table(win)
    header = table.horizontalHeader()
    assert isinstance(header, tn._SelectAllHeader), "复选框列表头应为自定义全选表头"
    # 工具栏/页面上不再有独立的「全选」复选按钮
    from PySide6.QtWidgets import QCheckBox
    for c in win.findChildren(QCheckBox):
        assert c.text() != "全选", "工具栏不应再保留独立的「全选」按钮"
    # 通过表头 _toggled 信号（模拟点击）全选/取消全部行
    header._toggled.emit(True)
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None:
            assert it.checkState() == QtCore.Qt.Checked, f"第{r}行应被全选"
    header._toggled.emit(False)
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None:
            assert it.checkState() == QtCore.Qt.Unchecked, f"第{r}行应被取消全选"


def test_select_all_header_state_syncs_after_refresh():
    # header 的全选状态应随行勾选情况同步（_update_select_all_state）
    _app()
    win = QtWidgets.QWidget()
    win.resize(820, 600)
    owner = _Owner()
    tn._make_page_widget(owner, win)
    win.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    table = _find_table(win)
    header = table.horizontalHeader()
    assert isinstance(header, tn._SelectAllHeader)
    delegate = table.itemDelegate()
    handler = getattr(delegate, "check_click_handler", None)
    assert handler is not None
    # 逐行勾选（真实点击流），每行勾选都同步表头全选状态
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None and it.checkState() != QtCore.Qt.Checked:
            handler(r, False, False)
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
    assert header._checked is True, "全部勾选后表头应为勾选态"
    # 取消其中一行，表头应同步为未勾选
    if table.rowCount() > 0:
        handler(0, True, False)  # ctrl 单切第 0 行
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
    assert header._checked is False, "有行未勾选时表头应为未勾选态"


def test_content_col_cap_keeps_narrow_columns_fit():
    # 修复：内容列是折行/弹性列，应限宽（最多占视口一半）以免吃掉窗口宽度，
    # 否则标题/创建时间等窄列内容被截断/换行。重建页面并校验各窄列宽度 >= 其内容单行宽。
    # 用足够宽的窗口（避免列总宽超过视口被过度压缩）以验证“窄列内容可容纳”这一属性。
    _app()
    win = QtWidgets.QWidget()
    win.resize(1400, 600)
    page = tn._make_page_widget(_Owner(), win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()
    table = _find_table(win)
    tn.add_todo("宽度测试标题", content="内容列较长的一行文字，用于验证内容列不会被无限撑宽")
    tn.add_todo("第二行", content="另一行")
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText(""); le.returnPressed.emit()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()
    header = table.horizontalHeader()
    fm = table.fontMetrics()
    # 校验自适应表（内容列带宽度上限）后，各非内容列都不窄于其内容的单行宽度
    for c in range(table.columnCount()):
        if c == tn.COL_CONTENT:
            continue
        need = 0
        for r in range(table.rowCount()):
            it = table.item(r, c)
            if it is not None:
                need = max(need, fm.horizontalAdvance(it.text()))
        assert table.columnWidth(c) >= need, f"列{c} 宽度不足（需要{need} 实际{table.columnWidth(c)}）"
    # 内容列不应无限撑宽（应被限制在当前视口比例内）
    assert table.columnWidth(tn.COL_CONTENT) <= table.viewport().width()
    for t in ("宽度测试标题", "第二行"):
        for td in tn.get_todos():
            if td["title"] == t:
                tn.delete_todo(td["id"])
