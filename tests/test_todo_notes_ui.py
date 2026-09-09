import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from PySide6.QtTest import QTest

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


def _ensure_test_data():
    if not tn.get_todos():
        tn.add_todo("__test_todo__", content="test content", priority=1, category="test_cat")


def _cleanup_test_data():
    for td in tn.get_todos():
        if td["title"] == "__test_todo__":
            tn.delete_todo(td["id"])


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
    _ensure_test_data()
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


def test_combo_popup_width_adapts_to_content():
    # 下拉编辑器弹出列表按内容自适应加宽：弹出视图最小宽度 >= 最宽项文字宽 + 内边距
    _ensure_test_data()
    win, page = _make_page()
    table = _find_table(win)
    delegate = tn._TodoItemDelegate(table)
    opt = QtWidgets.QStyleOptionViewItem()
    model = table.model()
    fm = table.fontMetrics()
    for col, label in ((tn.COL_CATEGORY, "类别"), (tn.COL_PRIORITY, "优先级"), (tn.COL_STATUS, "状态")):
        ed = delegate.createEditor(table, opt, model.index(0, col))
        assert isinstance(ed, QtWidgets.QComboBox)
        max_w = max(fm.horizontalAdvance(ed.itemText(i)) for i in range(ed.count()))
        assert ed.view().minimumWidth() >= max_w + 24, f"{label} 下拉弹出宽度应随内容加宽"
        ed.deleteLater()
    # 空列表守卫：无任何项时不抛错且不设置无意义宽度
    empty = delegate._make_combo(table, [])
    assert empty.view().minimumWidth() == 0 or empty.count() == 0
    empty.deleteLater()


def test_multiline_editor_widget_supported():
    _ensure_test_data()
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
    assert item.toolTip() == "", "内容列不再设置悬浮全文 tooltip"
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


def test_editing_content_row_height_adapts_to_wrapping():
    # 编辑内容时行高随换行实时自适应：不受 CONTENT_MAX_LINES 显示上限，安全上限 200 行
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    fm = editor.fontMetrics()
    capped = tn.CONTENT_MAX_LINES * (fm.lineSpacing() + 2) + 6
    # 输入远超 CONTENT_MAX_LINES 的多行文本 -> 行高应超过显示上限
    long_text = "\n".join("line %d " % i + "word " * 20 for i in range(12))
    editor.setPlainText(long_text)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    h = table.rowHeight(0)
    assert h > capped, "编辑期间行高应超过 CONTENT_MAX_LINES 显示上限"
    assert h >= 12 * (fm.lineSpacing() + 2) + 6, "行高应随实际折行行数展开"
    # 极端文本 -> 安全上限 200 行
    huge = "\n".join("x" * 5 for _ in range(300))
    editor.setPlainText(huge)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert table.rowHeight(0) <= 200 * (fm.lineSpacing() + 2) + 6, "行高不应超过 200 行安全上限"
    delegate.destroyEditor(editor, idx)
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
    # 确定性地固定内容列宽：行高断言只依赖当前行内容与字体度量，
    # 不依赖"此前其他测试在生产库留下的行"（2026-09 事故后测试一律使用独立空库）。
    # 150px 下 "short" 保持单行、多行样例折成 2+ 行，任一默认字体均成立。
    table.horizontalHeader().resizeSection(tn.COL_CONTENT, 150)
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
    _ensure_test_data()
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


def test_select_all_header_paints_button_text():
    # 需求1：全选表头改为带框文字按钮（未全选“全选”，全选后“取消”），绘制不抛错
    win, page = _make_page()
    table = _find_table(win)
    header = table.horizontalHeader()
    assert isinstance(header, tn._SelectAllHeader)
    # 首列宽度应足以容纳“取消”文字 + 内边距
    need = table.fontMetrics().horizontalAdvance("取消") + 24
    assert table.columnWidth(tn.COL_CHECK) >= need, \
        f"首列宽 {table.columnWidth(tn.COL_CHECK)} 应 >= {need}"
    # 两种状态下 paintSection 均不抛错（用真实 painter 绘制到 QPixmap）
    pm = QtGui.QPixmap(200, 40)
    painter = QtGui.QPainter(pm)
    try:
        rect = QtCore.QRect(0, 0, 60, 30)
        header.set_all_checked(False)
        header.paintSection(painter, rect, tn.COL_CHECK)
        header.set_all_checked(True)
        header.paintSection(painter, rect, tn.COL_CHECK)
    finally:
        painter.end()
    # 状态切换触发视口重绘（_checked 状态正确）
    header.set_all_checked(True)
    assert header._checked is True
    header.set_all_checked(False)
    assert header._checked is False


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


def test_select_all_persists_done_state():
    # 需求：全选/取消全选应持久化 done 状态到数据库（批量 UPDATE），refresh 后不丢失
    win, table, ids = _make_page_with_rows(3)
    header = table.horizontalHeader()
    assert isinstance(header, tn._SelectAllHeader)
    # 全选 -> DB 全部 done=1，表头同步为勾选态
    header._toggled.emit(True)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    todos = {t["id"]: t for t in tn.get_todos()}
    for i in ids:
        assert todos[i]["done"] == 1, f"全选后 {i} 应持久化为已完成"
    assert header._checked is True, "全选后表头应为勾选态"
    # 取消全选 -> DB 全部 done=0，表头同步为未勾选态
    header._toggled.emit(False)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    todos = {t["id"]: t for t in tn.get_todos()}
    for i in ids:
        assert todos[i]["done"] == 0, f"取消全选后 {i} 应持久化为未完成"
    assert header._checked is False, "取消全选后表头应为未勾选态"
    # refresh 后复选框状态与 DB 一致（勾选状态不丢失）
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None:
            assert it.checkState() == QtCore.Qt.Unchecked, "refresh 后复选框应与 DB 一致（未勾选）"
    for i in ids:
        tn.delete_todo(i)


def test_selectall_click_again_deselects():
    # 回归：全选后再次点击表头（模拟点击）应取消全部行勾选，并清空 DB 中所有行的 done 状态
    win, table, ids = _make_page_with_rows(3)
    header = table.horizontalHeader()
    assert isinstance(header, tn._SelectAllHeader)
    # 构造全选状态：先全选
    header._toggled.emit(True)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    todos = {t["id"]: t for t in tn.get_todos()}
    for i in ids:
        assert todos[i]["done"] == 1, "前置：全选后应全部已完成"
    # 再次点击表头（模拟点击）-> 取消全选
    header._toggled.emit(False)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # 所有行复选框取消勾选
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None:
            assert it.checkState() == QtCore.Qt.Unchecked, f"再次点击后第{r}行应取消勾选"
    # DB 中所有行 done 清空为 0
    todos = {t["id"]: t for t in tn.get_todos()}
    for i in ids:
        assert todos[i]["done"] == 0, f"再次点击后 {i} 的 done 应清空为 0"
    assert header._checked is False, "再次点击后表头应为未勾选态"
    for i in ids:
        tn.delete_todo(i)


def test_content_editor_geometry_covers_cell():
    # 项④：单行内容编辑器应覆盖（已展开的）单元格/行高矩形，而非默认的微小编辑器框
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    # 单行内容 + 默认行高 30
    table.setRowHeight(0, 30)
    # 模拟进入编辑状态（_editing_cell 指向该行内容列）
    delegate._editing_cell = (0, tn.COL_CONTENT)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.rect = table.visualRect(idx)
    delegate.updateEditorGeometry(editor, opt, idx)
    # 编辑器应精确覆盖单元格矩形（而非微小默认框）
    assert editor.geometry() == opt.rect, \
        f"编辑器几何 {editor.geometry()} 应等于单元格矩形 {opt.rect}"
    assert opt.rect.height() >= 28, "单元格矩形高度应至少为默认行高（非微小默认框）"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_content_editor_grows_and_no_scrollbar():
    # 项③：内容编辑器无内部滚动条，且行高随多行文本单调增长
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    # 无内部滚动条（grow-not-scroll）
    assert editor.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff, \
        "内容编辑器垂直滚动条应为 AlwaysOff"
    assert editor.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff, \
        "内容编辑器水平滚动条应为 AlwaysOff"
    # 行高随行数单调增长
    fm = editor.fontMetrics()
    prev = table.rowHeight(0)
    for n in (1, 3, 6, 10):
        editor.setPlainText("\n".join("line %d " % i + "word " * 20 for i in range(n)))
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        h = table.rowHeight(0)
        assert h >= prev, f"行高应随行数单调增长（{prev} -> {h}）"
        prev = h
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_inline_edit_aborts_on_stale_row_after_refresh():
    # 需求：单击延迟编辑在 refresh（行重建）后应中止，避免编辑到错误行
    win, table, ids = _make_page_with_rows(3)
    delegate = table.itemDelegate()
    # 单击第 0 行标题列 -> 挂起对 ids[0] 的延迟编辑（220ms）
    table.cellClicked.emit(0, tn.COL_TITLE)
    # 在定时器触发前删除 ids[0] 并刷新：row 0 现在指向 ids[1]（身份失效）
    tn.delete_todo(ids[0])
    le = [c for c in win.findChildren(QtWidgets.QLineEdit)][0]
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # 等待延迟编辑定时器触发
    QTest.qWait(300)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # 不应进入编辑状态（行身份已失效，不得编辑错误行）
    assert delegate._editing_cell is None, "refresh 后延迟编辑应中止，不得编辑错误行"
    for i in ids[1:]:
        tn.delete_todo(i)


def test_pending_click_after_window_close_no_crash():
    # 需求：窗口关闭（表格销毁）后，挂起的延迟编辑/延迟刷新不得触发 RuntimeError
    win, table, ids = _make_page_with_rows(1)
    table.cellClicked.emit(0, tn.COL_TITLE)   # 挂起延迟编辑
    win.deleteLater()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    QTest.qWait(300)   # 定时器若仍存活会在此触发
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    # 未崩溃即通过（定时器随页面销毁，且延迟回调有销毁守卫）
    for i in ids:
        tn.delete_todo(i)


def test_inline_edit_saves_via_item_changed():
    # 需求：行内编辑提交后经 itemChanged -> on_item_changed -> update_todo 持久化
    win, table, ids = _make_page_with_rows(1)
    item = table.item(0, tn.COL_TITLE)
    item.setText("__reset_row_edited")
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    todos = {t["id"]: t for t in tn.get_todos()}
    assert todos[ids[0]]["title"] == "__reset_row_edited", "行内编辑应经 itemChanged 持久化到 DB"
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Subprocess-isolated regression: inline-edit COL_CONTENT + refresh must not
# crash (0xC0000005 access violation on freed shiboken wrapper).
# Parent spawns child in a separate process so a hard crash kills only the
# child; the parent checks returncode.
# ---------------------------------------------------------------------------

def test_inline_edit_content_refresh_no_crash_subprocess():
    """Subprocess isolation: inline-edit COL_CONTENT + refresh must not crash (0xC0000005 guard)."""
    import subprocess
    from pathlib import Path
    child_name = "test_inline_edit_content_refresh_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_todo_notes_ui.py::{child_name}",
         "-q"],
        timeout=30,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


def test_inline_edit_content_refresh_no_crash_child():
    """Child: edit COL_CONTENT inline then trigger refresh — exercises the 0xC0000005 crash path.

    Crash mechanism: delegate.createEditor connects a per-keystroke lambda
    capturing the editor (shiboken wrapper) to textChanged.  When refresh()
    rebuilds the table (setRowCount) and destroys the active editor mid-edit,
    a pending lambda calls methods on a freed C++ object → hard crash that
    except Exception cannot catch.
    """
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from PySide6.QtTest import QTest
    from modules import todo_notes as tn

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    class _Owner:
        _page_refresh = None

    win = QtWidgets.QWidget()
    win.resize(820, 600)
    owner = _Owner()
    page = tn._make_page_widget(owner, win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()

    table = [c for c in win.findChildren(QtWidgets.QTableWidget)][0]

    # _make_page_widget sets owner._page_refresh = lambda: (refresh_categories(), refresh())
    refresh_fn = owner._page_refresh
    assert refresh_fn is not None, "_make_page_widget should set owner._page_refresh"

    # Ensure test data exists
    tid = tn.add_todo("__test_crash_sub__", content="crash test content",
                       priority=1, category="test")
    refresh_fn()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()

    try:
        item = table.item(0, tn.COL_CONTENT)
        assert item is not None, "COL_CONTENT item should exist"

        # Create inline editor via delegate (proven path; table has NoEditTriggers
        # so table.editItem() cannot open an editor — use delegate directly).
        delegate = table.itemDelegate()
        model = table.model()
        idx = model.index(0, tn.COL_CONTENT)
        editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
        delegate.setEditorData(editor, idx)

        # Type text — triggers textChanged → lambda captures editor (crash trigger)
        editor.setPlainText("new crash test text " * 20)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()

        # Simulate real keystrokes for additional textChanged events
        editor.setFocus()
        QTest.keyClicks(editor, " more typing to trigger textChanged")
        for _ in range(3):
            QtWidgets.QApplication.processEvents()

        # Trigger refresh while editor is still active — the crash path.
        # refresh() rebuilds table via setRowCount → destroys items and may
        # destroy the editor while the lambda still references it.
        refresh_fn()

        # Let events process: refresh rebuilds table → may destroy editor
        QTest.qWait(200)
        for _ in range(10):
            QtWidgets.QApplication.processEvents()

        # If we reached here, no crash occurred
    finally:
        for td in tn.get_todos():
            if td["title"] == "__test_crash_sub__":
                tn.delete_todo(td["id"])


# ---------------------------------------------------------------------------
# Task 2: Subprocess-isolated regression: destroying COL_CONTENT inline editor
# while textChanged signal is pending must not crash (0xC0000005 on freed
# shiboken wrapper).
# ---------------------------------------------------------------------------

def test_pending_text_changed_after_editor_destroy_no_crash_subprocess():
    """Subprocess isolation: destroy COL_CONTENT editor while textChanged pending must not crash (0xC0000005 guard)."""
    import subprocess
    from pathlib import Path
    child_name = "test_pending_text_changed_after_editor_destroy_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_todo_notes_ui.py::{child_name}",
         "-q"],
        timeout=30,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )


def test_pending_text_changed_after_editor_destroy_no_crash_child():
    """Child: destroy COL_CONTENT editor immediately after textChanged fires.

    Crash mechanism (delegate.py:143):
      editor.textChanged.connect(lambda: self._update_editing_row_height(editor, row))
    The lambda captures the editor (shiboken wrapper).  If destroyEditor is
    called while a textChanged emission is still pending in the event queue,
    the lambda fires on the freed C++ object → 0xC0000005 hard crash.
    """
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from PySide6.QtTest import QTest
    from modules import todo_notes as tn

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    class _Owner:
        _page_refresh = None

    win = QtWidgets.QWidget()
    win.resize(820, 600)
    owner = _Owner()
    page = tn._make_page_widget(owner, win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()

    table = [c for c in win.findChildren(QtWidgets.QTableWidget)][0]

    # _make_page_widget sets owner._page_refresh = lambda: (refresh_categories(), refresh())
    refresh_fn = owner._page_refresh
    assert refresh_fn is not None, "_make_page_widget should set owner._page_refresh"

    tid = None
    try:
        tid = tn.add_todo("__test_textchanged_destroy__",
                          content="pending signal test", priority=1, category="test")
        refresh_fn()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()

        delegate = table.itemDelegate()
        model = table.model()
        idx = model.index(0, tn.COL_CONTENT)
        editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
        delegate.setEditorData(editor, idx)

        # Trigger textChanged — setPlainText emits textChanged; the per-keystroke
        # lambda at delegate.py:143 captures editor (shiboken wrapper).
        editor.setPlainText("new pending signal text " * 10)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()

        # Simulate real keystrokes for additional textChanged emissions
        editor.setFocus()
        QTest.keyClicks(editor, " more keystrokes for pending signal")
        for _ in range(3):
            QtWidgets.QApplication.processEvents()

        # Now IMMEDIATELY destroy the editor while signals may still be pending.
        # destroyEditor frees the shiboken wrapper; any still-queued textChanged
        # lambda will then try to access the freed object → 0xC0000005 crash.
        delegate.destroyEditor(editor, idx)

        # Let pending signals settle on the event loop
        QTest.qWait(200)
        for _ in range(10):
            QtWidgets.QApplication.processEvents()

        # Process one more round to catch any deferred signal delivery
        QtWidgets.QApplication.processEvents()
    finally:
        for td in tn.get_todos():
            if td["title"] == "__test_textchanged_destroy__":
                tn.delete_todo(td["id"])
