"""todo_notes 常驻编辑器（todo 6）：每个可见单元格始终渲染为编辑控件。

覆盖：常驻编辑器安装、状态列可编辑下拉（选项来自 get_statuses）、悬停高亮边框
令牌、统一行高公式（编辑态 == 显示态，无 +1 加成）、无 220ms 防抖编辑态、
状态修改持久化 status_id、状态徽标颜色来自状态 color、内容自动换行、
不可见行编辑器销毁（防泄漏）。
"""
import os
import sys

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from PySide6.QtTest import QTest

from modules import todo_notes as tn
from modules import todo_store as _ts


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
    # 优先按 objectName 定位搜索框（常驻编辑器后 findChildren(QLineEdit)[0]
    # 会命中单元格编辑器）；objectName 尚未实现时回退到第一个 QLineEdit。
    le = win.findChild(QtWidgets.QLineEdit, "todo_search_input")
    if le is not None:
        return le
    return [c for c in win.findChildren(QtWidgets.QLineEdit)][0]


def _make_page_with_rows(n=3):
    win, page = _make_page()
    table = _find_table(win)
    ids = [tn.add_todo(f"__always_on{i}__", content="c") for i in range(n)]
    # 锁定行序：显式写入确定性时间（ids[0] 最新、往后递减）
    import sqlite3 as _sq
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
    le.setText("__always_on"); le.returnPressed.emit()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return win, table, ids


def _cleanup(ids):
    for i in ids:
        tn.delete_todo(i)


def test_always_on_editors_installed():
    """每个可见单元格始终渲染为编辑控件（常驻编辑器）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        # 标题 -> QLineEdit
        w = table.cellWidget(0, tn.COL_TITLE)
        assert isinstance(w, QtWidgets.QLineEdit), "标题列应有常驻 QLineEdit"
        # 内容 -> QPlainTextEdit
        w = table.cellWidget(0, tn.COL_CONTENT)
        assert isinstance(w, QtWidgets.QPlainTextEdit), "内容列应有常驻 QPlainTextEdit"
        # 类别 -> 可编辑 QComboBox
        w = table.cellWidget(0, tn.COL_CATEGORY)
        assert isinstance(w, QtWidgets.QComboBox), "类别列应有常驻 QComboBox"
        assert w.isEditable(), "类别列应为可编辑下拉框"
        # 优先级 -> QComboBox
        w = table.cellWidget(0, tn.COL_PRIORITY)
        assert isinstance(w, QtWidgets.QComboBox), "优先级列应有常驻 QComboBox"
        # 状态 -> 可编辑 QComboBox
        w = table.cellWidget(0, tn.COL_STATUS)
        assert isinstance(w, QtWidgets.QComboBox), "状态列应有常驻 QComboBox"
        assert w.isEditable(), "状态列应为可编辑下拉框"
        # 截止 -> QDateEdit
        w = table.cellWidget(0, tn.COL_DUE)
        assert isinstance(w, QtWidgets.QDateEdit), "截止列应有常驻 QDateEdit"
        # 勾选 / 创建时间 -> 无控件（delegate 绘制）
        assert table.cellWidget(0, tn.COL_CHECK) is None, "勾选列不应有控件"
        assert table.cellWidget(0, tn.COL_CREATED) is None, "创建时间列不应有控件"
    finally:
        _cleanup(ids)


def test_status_combo_editable_with_status_options():
    """状态列可编辑下拉，选项来自 get_statuses()，itemData 为 status_id。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        w = table.cellWidget(0, tn.COL_STATUS)
        assert w is not None and isinstance(w, QtWidgets.QComboBox)
        assert w.isEditable(), "状态列应为可编辑下拉框"
        statuses = {s["id"]: s["name"] for s in _ts.get_statuses()}
        assert w.count() == len(statuses), \
            f"状态选项数 {w.count()} 应 == get_statuses() 数 {len(statuses)}"
        for i in range(w.count()):
            sid = w.itemData(i)
            assert sid in statuses, f"选项 {i} 的 itemData {sid} 应为合法 status_id"
            assert w.itemText(i) == statuses[sid], \
                f"选项 {i} 文本 {w.itemText(i)} 应 == 状态名 {statuses[sid]}"
    finally:
        _cleanup(ids)


def test_editor_qss_uses_border_tokens():
    """编辑器 QSS 使用 todo_editor_border / todo_editor_border_hover 令牌。"""
    from core.theme.tokens import theme_palette
    win, table, ids = _make_page_with_rows(1)
    try:
        p = theme_palette()
        border = p["todo_editor_border"]
        hover = p["todo_editor_border_hover"]
        for col in (tn.COL_TITLE, tn.COL_CONTENT, tn.COL_CATEGORY,
                    tn.COL_PRIORITY, tn.COL_STATUS, tn.COL_DUE):
            w = table.cellWidget(0, col)
            assert w is not None, f"col {col} 应有常驻编辑器"
            qss = w.styleSheet()
            assert border in qss, f"col {col} QSS 应含 todo_editor_border 值 {border}"
            assert hover in qss, f"col {col} QSS 应含 todo_editor_border_hover 值 {hover}"
    finally:
        _cleanup(ids)


def test_unified_row_height_edit_equals_display():
    """统一行高公式：编辑态行高 == 显示态行高（无 +1 加成）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        text = "\n".join(f"line{i} " + "word " * 10 for i in range(5))
        tn.update_todo(ids[0], content=text)
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        fm = table.fontMetrics()
        sp = fm.lineSpacing()
        col_w = max(10, table.columnWidth(tn.COL_CONTENT) - tn.CONTENT_COL_PAD)

        def _expected(t):
            wrapped = len(tn._TodoItemDelegate._wrap_lines(t, fm, col_w))
            shown = min(max(1, wrapped), tn.CONTENT_SAFE_MAX_LINES)
            return shown * sp + 18

        display_h = table.rowHeight(0)
        assert abs(display_h - _expected(text)) < sp * 0.1, \
            f"显示态行高 {display_h} 应 == 统一公式 {_expected(text)}"
        editor = table.cellWidget(0, tn.COL_CONTENT)
        assert editor is not None
        # 编辑态输入更多内容：行高按统一公式增长（无 +1 加成）
        new_text = text + "\nline5 extra"
        editor.setPlainText(new_text)
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        edit_h = table.rowHeight(0)
        assert abs(edit_h - _expected(new_text)) < sp * 0.1, \
            f"编辑态行高 {edit_h} 应 == 统一公式 {_expected(new_text)}"
        assert abs(edit_h - display_h) < sp * 0.1 or edit_h > display_h, \
            "编辑态行高应随内容增长且与显示态同公式"
    finally:
        _cleanup(ids)


def test_no_click_debounce_edit_state():
    """单击单元格不进入编辑状态（常驻编辑器，无 220ms 防抖）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        table.cellClicked.emit(0, tn.COL_TITLE)
        QTest.qWait(300)  # 原防抖定时器窗口
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert table.state() != QtWidgets.QAbstractItemView.EditingState, \
            "单击不应进入编辑状态（常驻编辑器始终存在）"
        assert table.cellWidget(0, tn.COL_TITLE) is not None, \
            "常驻编辑器应始终存在"
    finally:
        _cleanup(ids)


def test_status_change_updates_db_status_id():
    """修改状态列下拉 -> 持久化 status_id（并推导 done）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        w = table.cellWidget(0, tn.COL_STATUS)
        assert w is not None
        statuses = {s["name"]: s["id"] for s in _ts.get_statuses()}
        done_id = statuses["已完成"]
        idx = w.findData(done_id)
        assert idx >= 0, "状态下拉应含「已完成」"
        w.setCurrentIndex(idx)
        w.activated.emit(idx)
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        todos = {t["id"]: t for t in _ts.get_todos()}
        assert todos[ids[0]]["status_id"] == done_id, \
            f"状态修改应持久化 status_id={done_id}"
        assert todos[ids[0]]["done"] == 1, "已完成状态应推导 done=1"
    finally:
        _cleanup(ids)


def test_status_badge_color_from_status_color():
    """状态徽标文字色来自状态 color（回退 todo_option_palette）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        statuses = _ts.get_statuses()
        done = next(s for s in statuses if s["name"] == "已完成")
        _ts.set_status_color(done["id"], "#123456")
        # 刷新重建编辑器（读取新颜色）
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        w = table.cellWidget(0, tn.COL_STATUS)
        assert w is not None
        idx = w.findData(done["id"])
        w.setCurrentIndex(idx)
        w.activated.emit(idx)
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        item = table.item(0, tn.COL_STATUS)
        assert item is not None
        assert item.foreground().color().name() == "#123456", \
            f"状态文字色应来自状态 color，实际 {item.foreground().color().name()}"
    finally:
        _cleanup(ids)


def test_content_editor_wraps_at_word_boundary():
    """内容编辑器自动换行（WrapAtWordBoundaryOrAnywhere）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        w = table.cellWidget(0, tn.COL_CONTENT)
        assert w is not None
        assert w.wordWrapMode() == QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere, \
            "内容编辑器应自动换行（WrapAtWordBoundaryOrAnywhere）"
    finally:
        _cleanup(ids)


def test_editors_destroyed_for_invisible_rows():
    """滚动后不可见行的编辑器被销毁（防泄漏）。"""
    win, table, ids = _make_page_with_rows(20)
    try:
        win.resize(820, 80)
        for _ in range(10):
            QtWidgets.QApplication.processEvents()
        # 顶部行可见，有编辑器
        assert table.cellWidget(0, tn.COL_TITLE) is not None, "顶部行应有编辑器"
        table.scrollToBottom()
        for _ in range(10):
            QtWidgets.QApplication.processEvents()
        # 滚动后第 0 行不可见，编辑器应被销毁
        assert table.cellWidget(0, tn.COL_TITLE) is None, \
            "不可见行的编辑器应被销毁（防泄漏）"
    finally:
        _cleanup(ids)