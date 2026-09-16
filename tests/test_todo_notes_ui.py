import os
import sys

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from PySide6.QtTest import QTest

from ui.adaptive_table import make_adaptive_table
from modules import todo_notes as tn

# 子进程隔离（0xC0000005 保护）：_child 用例只在其父用例 spawn 的子进程里运行。
# 主套件收集到 _child 时一律 skip——子进程里由父用例注入 _YZ_SUBPROCESS_CHILD=1。
# 背景：_child 用例在线程内进程里跑会留下 Qt 事件循环残留（已销毁编辑器的
# 待发信号/deferred timer），后续整页构建的 processEvents() 会触发
# Windows access violation（2026-09-16 CI 崩溃：test_content_row_height… 在
# _make_page 的 processEvents 处原生崩溃）。
_SUBPROCESS_CHILD = pytest.mark.skipif(
    "os.environ.get('_YZ_SUBPROCESS_CHILD') != '1'",
    reason="仅在子进程隔离中运行（0xC0000005 崩溃保护）；主套件跳过",
)


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


def _search_input(win):
    # 常驻编辑器后 findChildren(QLineEdit)[0] 会命中单元格编辑器，
    # 必须按 objectName 定位搜索框；objectName 尚未实现时回退到第一个 QLineEdit。
    le = win.findChild(QtWidgets.QLineEdit, "todo_search_input")
    if le is not None:
        return le
    return [c for c in win.findChildren(QtWidgets.QLineEdit)][0]


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

    # 状态列应为可编辑下拉框（选项来自 get_statuses）
    ed_status = delegate.createEditor(table, opt, model.index(0, tn.COL_STATUS))
    assert ed_status.isEditable(), "状态列应为可编辑下拉框"
    ed_status.deleteLater()

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
    expected = min(max(1, wrapped), tn.CONTENT_SAFE_MAX_LINES) * sp + 18
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
    # 锁定行序：created_at 是秒级时间戳，连续 add 在 CI 慢环境下可能跨秒，
    # 而默认排序为 created_at DESC —— 跨秒时行序反转、同秒时顺序未定义，
    # 导致 table 行 i 不再恒等于 ids[i]（历史 flaky：DB id 级断言偶发失败）。
    # 显式写入确定性时间（ids[0] 最新、往后递减），使刷新后行序恒为插入序
    # [ids[0], ids[1], ..., ids[n-1]]（多测试依赖 row i == ids[i] 语义）。
    import sqlite3 as _sq
    from modules import todo_store as _ts
    _conn = _sq.connect(_ts.DB_PATH)  # conftest 已 patch 到临时库
    _conn.execute("PRAGMA journal_mode=WAL")
    for _i, _tid in enumerate(ids):
        _conn.execute(
            "UPDATE todo_notes SET created_at=? WHERE id=?",
            (f"2020-01-01 00:00:{n - 1 - _i:02d}", _tid),
        )
    _conn.commit()
    _conn.close()
    le = _search_input(win)
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
    le = _search_input(win)
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    item = table.item(0, tn.COL_CONTENT)
    assert item.text() == long_text, "应保留完整内容而非截断"
    assert item.toolTip() == "", "内容列不再设置悬浮全文 tooltip"
    # 行高不应超过 CONTENT_SAFE_MAX_LINES 行
    fm = table.fontMetrics()
    capped_h = tn.CONTENT_SAFE_MAX_LINES * fm.lineSpacing() + 18
    assert table.rowHeight(0) <= capped_h
    for i in ids:
        tn.delete_todo(i)


def test_editing_content_row_height_adapts_to_wrapping():
    # T2（todo 6 统一公式）: 编辑内容时行高 == shown*sp+18（无 +1 加成），与显示态一致
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    # 编辑器打开后 setEditorData 会立即调用 _update_editing_row_height
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    fm = editor.fontMetrics()
    sp = fm.lineSpacing()
    # 输入 20 行短文本（每行不折行 → wrapped == 20 < 200 安全上限）
    text_20 = "\n".join(f"line {i}" for i in range(20))
    editor.setPlainText(text_20)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # 统一公式：编辑高度 == 显示高度 == shown*sp+18（无 +1 行空隙）
    wrapped = len(tn._TodoItemDelegate._wrap_lines(
        text_20, fm, max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)))
    shown = min(max(1, wrapped), tn.CONTENT_SAFE_MAX_LINES)
    expected = shown * sp + 18
    edit_h = table.rowHeight(0)
    assert edit_h == expected, f"编辑高度 {edit_h} 应 == 统一公式 {expected}"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_single_line_rows_not_forced_to_six_lines():
    # 修复：初次打开时单行内容不应被窄列宽折行成 6 行；内容列宽变化后应按实际行数重算
    win, page = _make_page()
    table = _find_table(win)
    id1 = tn.add_todo("__reset_single", content="short")
    id2 = tn.add_todo("__reset_multi", content="\n".join("row%d " % i + "word " * 8 for i in range(8)))
    le = _search_input(win)
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
    one = 1 * sp + 18
    capped = tn.CONTENT_SAFE_MAX_LINES * sp + 18
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
    le = _search_input(win)
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
    le = _search_input(win)
    le.setText("__reset_row"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    for r in range(table.rowCount()):
        it = table.item(r, tn.COL_CHECK)
        if it is not None:
            assert it.checkState() == QtCore.Qt.Unchecked, "refresh 后复选框应与 DB 一致（未勾选）"
    for i in ids:
        tn.delete_todo(i)





def test_content_editor_geometry_covers_cell():
    # 项④（todo 6 常驻编辑器）：内容编辑器应覆盖（已展开的）单元格/行高矩形
    win, table, ids = _make_page_with_rows(1)
    idx = table.model().index(0, tn.COL_CONTENT)
    # 常驻内容编辑器由 setCellWidget 管理几何，应覆盖单元格矩形
    editor = table.cellWidget(0, tn.COL_CONTENT)
    assert editor is not None, "内容列应有常驻编辑器"
    rect = table.visualRect(idx)
    geo = editor.geometry()
    assert abs(geo.x() - rect.x()) <= 2 and abs(geo.y() - rect.y()) <= 2, \
        f"编辑器几何 {geo} 应覆盖单元格矩形 {rect}"
    assert geo.width() >= rect.width() - 2 and geo.height() >= rect.height() - 2, \
        f"编辑器尺寸 {geo} 应覆盖单元格 {rect}"
    assert rect.height() >= 28, "单元格矩形高度应至少为默认行高（非微小默认框）"
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


def test_click_does_not_enter_edit_state():
    # 需求（todo 6）：常驻编辑器下单击单元格不进入编辑状态（无 220ms 防抖）
    win, table, ids = _make_page_with_rows(3)
    table.cellClicked.emit(0, tn.COL_TITLE)
    QTest.qWait(300)  # 原防抖定时器窗口
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert table.state() != QtWidgets.QAbstractItemView.EditingState, \
        "单击不应进入编辑状态（常驻编辑器始终存在）"
    assert table.cellWidget(0, tn.COL_TITLE) is not None, \
        "常驻编辑器应始终存在"
    for i in ids:
        tn.delete_todo(i)


def test_pending_click_after_window_close_no_crash():
    # 需求（todo 6）：窗口关闭（表格销毁）后，单击不得触发 RuntimeError
    win, table, ids = _make_page_with_rows(1)
    table.cellClicked.emit(0, tn.COL_TITLE)
    win.deleteLater()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    QTest.qWait(300)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    # 未崩溃即通过
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
        env={**os.environ, "_YZ_SUBPROCESS_CHILD": "1"},
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


@_SUBPROCESS_CHILD
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
        env={**os.environ, "_YZ_SUBPROCESS_CHILD": "1"},
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


@_SUBPROCESS_CHILD
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


# ---------------------------------------------------------------------------
# Task 1 regression: CONTENT_SAFE_MAX_LINES = 200, content-driven row heights
# ---------------------------------------------------------------------------

def test_content_safe_max_lines_is_200():
    """Task 1: CONTENT_SAFE_MAX_LINES 应为 200（显示/编辑统一安全上限）。"""
    assert tn.CONTENT_SAFE_MAX_LINES == 200


def test_content_row_height_scales_with_actual_lines_subprocess():
    """Subprocess isolation: row-height scaling assertions run in a fresh process.

    2026-09-16 CI 崩溃：本用例在主进程内 _make_page() 的 30×processEvents()
    处触发 Windows access violation（前面用例留在事件循环里的已销毁编辑器
    信号被这里处理）。改成父/子进程隔离——子进程拥有全新的 QApplication，
    零残留状态，原生崩溃只杀死子进程，父用例按 returncode 报告。
    """
    import subprocess
    from pathlib import Path
    child_name = "test_content_row_height_scales_with_actual_lines_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_todo_notes_ui.py::{child_name}",
         "-q"],
        timeout=30,
        capture_output=True,
        env={**os.environ, "_YZ_SUBPROCESS_CHILD": "1"},
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


@_SUBPROCESS_CHILD
def test_content_row_height_scales_with_actual_lines_child():
    """Child: T2 行高断言——20 行内容折行高度 == min(wrapped,200)*sp+18。

    单独在子进程运行（父用例 _subprocess 注入 _YZ_SUBPROCESS_CHILD=1）。
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
    page = tn._make_page_widget(_Owner(), win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()

    table = [c for c in win.findChildren(QtWidgets.QTableWidget)][0]

    if not tn.get_todos():
        tn.add_todo("__test_todo__", content="test content", priority=1, category="test_cat")

    id_short = tn.add_todo("__tg1_short__", content="line0\nline1\nline2")
    id_long = tn.add_todo("__tg1_long__", content="\n".join(f"line{i} " + "word " * 10 for i in range(10)))
    le = _search_input(win)
    le.setText("__tg1_"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    rows = {table.item(r, tn.COL_TITLE).text(): r for r in range(table.rowCount())}
    r_short = rows.get("__tg1_short__")
    r_long = rows.get("__tg1_long__")
    assert r_short is not None and r_long is not None, "测试行应存在"
    h_short = table.rowHeight(r_short)
    h_long = table.rowHeight(r_long)
    assert h_short < h_long, f"3 行内容行高 {h_short} 应 < 10 行内容行高 {h_long}"
    # T2: 超 12 行内容应显示为完整折行高度（不截断到 12 行），行高 == min(wrapped,200)*sp+18
    id_over = tn.add_todo("__tg1_over__", content="\n".join(f"over{i} " + "word " * 10 for i in range(20)))
    le.setText("__tg1_"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    rows2 = {table.item(r, tn.COL_TITLE).text(): r for r in range(table.rowCount())}
    r_over = rows2.get("__tg1_over__")
    assert r_over is not None
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    # 20 行内容 → 完整高度（不超过 CONTENT_SAFE_MAX_LINES 时无截断）
    text_over = "\n".join(f"over{i} " + "word " * 10 for i in range(20))
    wrapped_over = len(tn._TodoItemDelegate._wrap_lines(
        text_over, fm, max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)))
    shown_over = min(max(1, wrapped_over), tn.CONTENT_SAFE_MAX_LINES)
    expected_h = shown_over * sp + 18
    actual_h = table.rowHeight(r_over)
    assert actual_h == expected_h, f"20 行内容行高 {actual_h} 应 == 完整折行高度 {expected_h}"
    for td in tn.get_todos():
        if td["title"].startswith("__tg1_"):
            tn.delete_todo(td["id"])


# ---------------------------------------------------------------------------
# Task 2 regression: content editor has no internal scrollbars (AlwaysOff)
# ---------------------------------------------------------------------------

def test_content_editor_scrollbar_policies_always_off():
    """Task 2: 内容编辑器垂直/水平滚动条策略均为 ScrollBarAlwaysOff（无内部滚动条）。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    assert editor.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff, \
        "内容编辑器垂直滚动条应为 ScrollBarAlwaysOff"
    assert editor.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff, \
        "内容编辑器水平滚动条应为 ScrollBarAlwaysOff"
    # 200 行安全上限仍生效：极端文本编辑行高不超过 200 行（统一公式无 +1 空隙）
    fm = editor.fontMetrics()
    huge = "\n".join("x" * 5 for _ in range(300))
    editor.setPlainText(huge)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert table.rowHeight(0) <= tn.CONTENT_SAFE_MAX_LINES * fm.lineSpacing() + 18, \
        "行高不应超过 200 行安全上限"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 2 (T2) new tests: full-height display, +1 slack editing, vertical centering
# ---------------------------------------------------------------------------

def test_content_200line_safety_cap_display_and_edit():
    """T2(a)（todo 6 统一公式）: 300 行内容 → 显示行高 == 200*sp+18，编辑行高 == 200*sp+18。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    huge = "\n".join(f"line{i} " + "x" * 5 for i in range(300))
    # 显示态：直接设置 item text 并 fit
    item = table.item(0, tn.COL_CONTENT)
    item.setText(huge)
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    display_h = table.rowHeight(0)
    assert display_h == tn.CONTENT_SAFE_MAX_LINES * sp + 18, \
        f"300 行内容显示行高 {display_h} 应 == 200*sp+18 = {200 * sp + 18}"
    # 编辑态：editor setPlainText 300 行
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    editor.setPlainText(huge)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    edit_h = table.rowHeight(0)
    assert edit_h == tn.CONTENT_SAFE_MAX_LINES * sp + 18, \
        f"300 行内容编辑行高 {edit_h} 应 == 200*sp+18 = {200 * sp + 18}"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_edit_overflow_viewport_always_off():
    """T2(b)（todo 6 统一公式）: 小视口 + 20 段内容 → ScrollBarAlwaysOff 且行高跟随
    统一公式（折行数封顶 CONTENT_SAFE_MAX_LINES，无 +1 空隙），超出视口仍扩大。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    # 缩小视口：窄列导致 20 段文本折行数远超 200，恰好覆盖封顶分支
    table.resize(800, 60)
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    text_20 = "\n".join(f"line{i} " + "word " * 20 for i in range(20))
    editor.setPlainText(text_20)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert editor.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff, \
        "内容编辑器滚动条应始终为 ScrollBarAlwaysOff"
    fm = editor.fontMetrics()
    sp = fm.lineSpacing()
    wrapped = len(tn._TodoItemDelegate._wrap_lines(
        text_20, fm, max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)))
    # 行高公式必须与 delegate._update_editing_row_height 完全一致：折行数封顶（无 +1 空隙）
    lines = min(max(1, wrapped), tn.CONTENT_SAFE_MAX_LINES)
    expected_h = lines * sp + 18
    assert table.rowHeight(0) == expected_h, \
        f"行高 {table.rowHeight(0)} 应 == {expected_h}"
    assert table.rowHeight(0) > table.viewport().height(), \
        "行高应超出视口高度"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_edit_vertical_centering():
    """T2(c)（todo 6 统一公式）: 3 行内容编辑中 → viewportMargins 全 0（编辑器填满单元格，无 +1 空隙居中）。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    text_3 = "line0\nline1\nline2"
    editor.setPlainText(text_3)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    margins = editor.viewportMargins()
    assert margins.top() == 0, \
        f"viewportMargins.top {margins.top()} 应 == 0（统一公式无 +1 空隙）"
    assert margins.bottom() == 0, \
        f"viewportMargins.bottom {margins.bottom()} 应 == 0（统一公式无 +1 空隙）"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


def test_edit_capped_overflow_no_margins():
    """T2(d): 300 行内容编辑中 → 4 个 viewportMargins 全 0（顶部对齐兜底）。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    huge = "\n".join(f"line{i} " + "x" * 5 for i in range(300))
    editor.setPlainText(huge)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    margins = editor.viewportMargins()
    assert margins.top() == 0, f"viewportMargins.top 应 == 0 (capped overflow)，实际 {margins.top()}"
    assert margins.bottom() == 0, f"viewportMargins.bottom 应 == 0 (capped overflow)，实际 {margins.bottom()}"
    assert margins.left() == 0, f"viewportMargins.left 应 == 0"
    assert margins.right() == 0, f"viewportMargins.right 应 == 0"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 3 regression: display row height formula unified with edit-state
# ---------------------------------------------------------------------------

def test_display_height_matches_edit_height_formula():
    """T2（todo 6 统一公式）: 展示态行高 == 编辑态行高 == shown*sp+18（无 +1 行空隙）。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CONTENT)
    fm = table.fontMetrics()
    sp = fm.lineSpacing()
    # 展示态：按当前内容折行数计算行高
    text = idx.data() or ""
    wrapped = len(tn._TodoItemDelegate._wrap_lines(
        text, fm, max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)))
    shown = min(max(1, wrapped), tn.CONTENT_SAFE_MAX_LINES)
    display_h = table.rowHeight(0)
    assert abs(display_h - (shown * sp + 18)) < sp * 0.1, \
        f"展示态行高 {display_h} 应等于 {shown} * lineSpacing + 18 = {shown * sp + 18}"
    # 编辑态：同一内容展开后的行高公式（统一公式，无 +1 行空隙）
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    delegate.setEditorData(editor, idx)
    delegate._update_editing_row_height(editor, 0)
    edit_h = table.rowHeight(0)
    assert abs(edit_h - (shown * sp + 18)) < sp * 0.1, \
        f"编辑态行高 {edit_h} 应等于 {shown} * lineSpacing + 18 = {shown * sp + 18}"
    # 编辑态与展示态行高一致（统一公式）
    assert abs(edit_h - display_h) < sp * 0.1, \
        f"编辑态行高 {edit_h} 与展示态行高 {display_h} 应一致（统一公式）"
    delegate.destroyEditor(editor, idx)
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 4 regression: check column has no editable area
# ---------------------------------------------------------------------------

def test_check_column_not_editable():
    """Task 4: COL_CHECK item flags 不含 ItemIsEditable，且不创建编辑器。"""
    win, table, ids = _make_page_with_rows(1)
    check = table.item(0, tn.COL_CHECK)
    assert check is not None
    assert not (check.flags() & QtCore.Qt.ItemIsEditable), \
        "复选框列 item 不应含 ItemIsEditable"
    # 复选框列仍可勾选（不改变勾选语义）
    assert check.flags() & QtCore.Qt.ItemIsUserCheckable
    # delegate 不为复选框列创建编辑器（无 COL_CHECK 分支，且 item 不可编辑）
    delegate = table.itemDelegate()
    model = table.model()
    idx = model.index(0, tn.COL_CHECK)
    editor = delegate.createEditor(table, QtWidgets.QStyleOptionViewItem(), idx)
    assert editor is None, "复选框列不应创建编辑器"
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 1 (all-todos plan): 已完成项整行特别浅的浅绿色背景
# ---------------------------------------------------------------------------

def test_done_row_fills_light_green_background():
    """已完成行整行浅绿色背景：done=1 行 paint 触发 fillRect，done=0 行不触发。"""
    from unittest.mock import patch
    from core.theme.tokens import theme_palette, rgba_to_qcolor

    _app()
    win = QtWidgets.QWidget()
    win.resize(820, 600)
    page = tn._make_page_widget(_Owner(), win)
    lay = QtWidgets.QVBoxLayout(win)
    lay.addWidget(page)
    win.show()
    for _ in range(30):
        QtWidgets.QApplication.processEvents()
    table = _find_table(win)

    # 构造 done=1 与 done=0 两行
    tid_done = tn.add_todo("__test_done_bg__", content="done", priority=1)
    tn.update_todo(tid_done, done=1)
    tid_undone = tn.add_todo("__test_undone_bg__", content="undone", priority=1)
    tn.update_todo(tid_undone, done=0)
    le = _search_input(win)
    le.setText("__test_"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()

    rows = {table.item(r, tn.COL_TITLE).text(): r for r in range(table.rowCount())}
    r_done = rows.get("__test_done_bg__")
    r_undone = rows.get("__test_undone_bg__")
    assert r_done is not None and r_undone is not None, "测试行应存在"

    delegate = table.itemDelegate()
    model = table.model()

    img = QtGui.QImage(400, 40, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(img)

    def _opt(row, col):
        idx = model.index(row, col)
        opt = QtWidgets.QStyleOptionViewItem()
        opt.rect = QtCore.QRect(0, 0, 400, 40)
        opt.fontMetrics = table.fontMetrics()
        opt.state = QtWidgets.QStyle.StateFlag.State_Enabled
        return opt, idx

    try:
        # done 行：paint 应触发 fillRect，且填充色为浅绿色令牌
        opt, idx = _opt(r_done, tn.COL_TITLE)
        with patch.object(QtGui.QPainter, "fillRect") as mock_fill:
            delegate.paint(painter, opt, idx)
            assert mock_fill.call_count >= 1, "done 行应触发 fillRect（浅绿色背景）"
            expected = rgba_to_qcolor(theme_palette()["todo_done_bg"])
            assert mock_fill.call_args[0][1] == expected, \
                f"fillRect 颜色应为浅绿令牌 {expected.name()}"

        # 未 done 行：paint 不应触发 fillRect
        opt2, idx2 = _opt(r_undone, tn.COL_TITLE)
        with patch.object(QtGui.QPainter, "fillRect") as mock_fill:
            delegate.paint(painter, opt2, idx2)
            assert mock_fill.call_count == 0, "未完成行不应触发 fillRect"
    finally:
        painter.end()
        for td in tn.get_todos():
            if td["title"].startswith("__test_"):
                tn.delete_todo(td["id"])


# ---------------------------------------------------------------------------
# Task 3 (T3): custom centered checkbox in check column (paint branch)
# ---------------------------------------------------------------------------

def _paint_check_cell(table, delegate, row, checked, fm):
    """把 COL_CHECK 单元格画进 QImage 并返回图像。checked=True 时先置勾选态。"""
    item = table.item(row, tn.COL_CHECK)
    if item is not None:
        item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
    img = QtGui.QImage(200, 200, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.white)
    painter = QtGui.QPainter(img)
    try:
        idx = table.model().index(row, tn.COL_CHECK)
        opt = QtWidgets.QStyleOptionViewItem()
        opt.rect = QtCore.QRect(0, 0, 200, 200)
        opt.fontMetrics = fm
        opt.state = QtWidgets.QStyle.StateFlag.State_Enabled
        delegate.paint(painter, opt, idx)
    finally:
        painter.end()
    return img





def test_check_col_paint_render_diff():
    """T3(b): 勾选与未勾选渲染像素不同，且勾选态复选框居中绘制（accent 填充 + 白对勾）。"""
    win, table, ids = _make_page_with_rows(1)
    delegate = table.itemDelegate()
    fm = table.fontMetrics()
    img_unchecked = _paint_check_cell(table, delegate, 0, False, fm)
    img_checked = _paint_check_cell(table, delegate, 0, True, fm)
    a = bytes(img_unchecked.bits())
    b = bytes(img_checked.bits())
    assert a != b, "勾选与未勾选渲染应不同（对勾/填充已画出）"
    # 自定义复选框居中绘制：未勾选中心为背景白（空框内部），勾选中心被
    # accent 填充/白对勾覆盖（非白）。默认 Qt 指示器画在左缘、中心恒为白
    # —— 该断言在自绘前必失败。
    center_unchecked = img_unchecked.pixelColor(100, 100)
    center_checked = img_checked.pixelColor(100, 100)
    assert center_unchecked == QtGui.QColor(QtCore.Qt.white), \
        f"未勾选态中心 {center_unchecked.name()} 应为背景白（空框内部）"
    assert center_checked != QtGui.QColor(QtCore.Qt.white), \
        f"勾选态中心 {center_checked.name()} 应被 accent 填充/对勾覆盖（复选框居中）"
    for i in ids:
        tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 4 (T4): remove alternating row colors, strengthen grid borders,
#              warm-neutral done-row background
# ---------------------------------------------------------------------------

def test_alternating_row_colors_disabled():
    """T4(a): table.setAlternatingRowColors 应为 False。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        assert table.alternatingRowColors() is False, \
            "setAlternatingRowColors 应为 False（取消奇偶底色）"
    finally:
        for i in ids:
            tn.delete_todo(i)


def test_table_grid_border_qss():
    """T4(b): QSS 应含 gridline-color(border_strong)、不含 :alternate、不含 }}。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        qss = table.styleSheet()
        # 应含 gridline-color
        assert "gridline-color" in qss, \
            f"QSS 应含 gridline-color 规则，实际: {qss[:200]}"
        # gridline-color 的值应含 border_strong 令牌展开值
        from core.theme.tokens import theme_palette
        bs = theme_palette()["border_strong"]
        assert bs in qss, \
            f"QSS 应含 border_strong 值 '{bs}'，实际: {qss[:200]}"
        # 不应含 :alternate 规则
        assert ":alternate" not in qss, \
            f"QSS 不应含 :alternate 规则，实际: {qss[:200]}"
        # 不应含 }} 双花括号（QSS 语法错误）
        assert "}}" not in qss, \
            f"QSS 不应含 '}}' 双花括号，实际: {qss[:200]}"
    finally:
        for i in ids:
            tn.delete_todo(i)


def test_done_bg_value_dual_theme():
    """T4(c): 暗/亮双主题下 todo_done_bg 均为暖中性 rgba(180,160,140,0.12)。"""
    from core.theme.tokens import theme_palette
    expected = "rgba(180,160,140,0.12)"
    for dark in (True, False):
        pal = theme_palette(dark=dark)
        assert pal["todo_done_bg"] == expected, \
            f"dark={dark} 时 todo_done_bg 应为 '{expected}'，实际 '{pal['todo_done_bg']}'"


# ---------------------------------------------------------------------------
# Task 5 (T5): regression test — content edits reset done to 0
# ---------------------------------------------------------------------------

def test_content_edit_resets_done():
    """T5: 内联编辑内容列时，done=1 → done=0，新内容持久化到 DB。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        # 先置为 done=1
        tn.update_todo(ids[0], done=1)
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[ids[0]]["done"] == 1, "前置条件：done 应为 1"

        # 触发真实内联编辑：修改内容列 → on_item_changed → COL_CONTENT 分支
        table.item(0, tn.COL_CONTENT).setText("修改后的内容")
        for _ in range(5):
            QtWidgets.QApplication.processEvents()

        # 断言：done 被重置为 0，新内容已持久化
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[ids[0]]["done"] == 0, \
            f"内容修改应重置 done=0，实际 done={todos[ids[0]]['done']}"
        assert todos[ids[0]]["content"] == "修改后的内容", \
            f"新内容应持久化，实际 content='{todos[ids[0]]['content']}'"
    finally:
        for i in ids:
            tn.delete_todo(i)


# ---------------------------------------------------------------------------
# Task 13 (T13): content edits must reset BOTH done AND status_id to 待办
# ---------------------------------------------------------------------------
# 背景：todo 2 引入 status_id 后，状态列渲染改由 status_id 驱动。旧实现只把
# done 置 0 而不同步 status_id，导致"done 归零但状态显示没变"（用户报告
# "没看到生效"）。以下用例直接读 DB（不经 _get_conn 的迁移校正），锁定
# done 与 status_id 两列同步归零。

def _raw_todo_row(tid):
    """绕过迁移校正直接读 DB 行（done, status_id），锁定 update_todo 的真实写入。"""
    import sqlite3 as _sq
    from modules import todo_store as _ts
    conn = _sq.connect(_ts.DB_PATH)
    try:
        return conn.execute(
            "SELECT done, status_id FROM todo_notes WHERE id = ?", (tid,)
        ).fetchone()
    finally:
        conn.close()


def _status_ids():
    from modules import todo_store as _ts
    statuses = _ts.get_statuses()
    return {
        "待办": next(s["id"] for s in statuses if s["name"] == "待办"),
        "已完成": next(s["id"] for s in statuses if s["name"] == "已完成"),
    }


def test_content_edit_resets_status_id_to_todo():
    """T13: 内联编辑内容列时，done=1 → done=0 且 status_id 指向内置「待办」。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        sids = _status_ids()
        # 前置：标记为已完成（done=1，status_id 指向「已完成」）
        tn.update_todo(ids[0], done=1)
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[ids[0]]["done"] == 1, "前置：done 应为 1"
        assert todos[ids[0]]["status_id"] == sids["已完成"], \
            "前置：status_id 应指向已完成"

        # 触发真实内联编辑：修改内容列 → on_item_changed → COL_CONTENT 分支
        table.item(0, tn.COL_CONTENT).setText("修改后的内容")
        for _ in range(5):
            QtWidgets.QApplication.processEvents()

        # 直接读 DB（不经迁移校正），断言 done 与 status_id 同步归零
        done, status_id = _raw_todo_row(ids[0])
        assert done == 0, f"内容修改应重置 done=0，实际 done={done}"
        assert status_id == sids["待办"], \
            f"内容修改应重置 status_id=待办，实际 status_id={status_id}"
    finally:
        for i in ids:
            tn.delete_todo(i)


def test_modal_content_change_resets_status_id_to_todo():
    """T13: 模态对话框修改内容 → done=0 且 status_id 指向内置「待办」。"""
    tid = tn.add_todo("__modal_reset__", content="orig", priority=1)
    try:
        sids = _status_ids()
        tn.update_todo(tid, done=1)
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[tid]["status_id"] == sids["已完成"], \
            "前置：status_id 应指向已完成"

        tn._maybe_reset_done_on_content_change(tid, "orig", "new content")

        done, status_id = _raw_todo_row(tid)
        assert done == 0, f"内容修改应重置 done=0，实际 done={done}"
        assert status_id == sids["待办"], \
            f"内容修改应重置 status_id=待办，实际 status_id={status_id}"
    finally:
        tn.delete_todo(tid)


def test_same_content_keeps_status_id():
    """T13: 内容改为相同值时不重置（done 与 status_id 均保持）。"""
    tid = tn.add_todo("__same_content__", content="orig", priority=1)
    try:
        sids = _status_ids()
        tn.update_todo(tid, done=1)
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[tid]["status_id"] == sids["已完成"], \
            "前置：status_id 应指向已完成"

        tn._maybe_reset_done_on_content_change(tid, "orig", "orig")

        done, status_id = _raw_todo_row(tid)
        assert done == 1, f"内容未变不应重置 done，实际 done={done}"
        assert status_id == sids["已完成"], \
            f"内容未变不应重置 status_id，实际 status_id={status_id}"
    finally:
        tn.delete_todo(tid)


def test_status_only_change_keeps_content_and_done():
    """T13: 只改状态不改内容时，内容重置逻辑不触发（done/status_id 跟随状态）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        sids = _status_ids()
        # 通过状态列常驻下拉改为「已完成」
        combo = table.cellWidget(0, tn.COL_STATUS)
        assert combo is not None, "状态列应有常驻下拉"
        idx = combo.findData(sids["已完成"])
        assert idx >= 0, "状态下拉应含「已完成」"
        combo.setCurrentIndex(idx)
        combo.activated.emit(idx)
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[ids[0]]["done"] == 1, "状态改为已完成应推导 done=1"
        assert todos[ids[0]]["status_id"] == sids["已完成"], \
            "status_id 应指向已完成"
        assert todos[ids[0]]["content"] == "c", "只改状态不应改动内容"
    finally:
        for i in ids:
            tn.delete_todo(i)
