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
        # 截止 -> 容器（只读 QDateEdit + 清除按钮）
        w = table.cellWidget(0, tn.COL_DUE)
        assert isinstance(w, QtWidgets.QWidget), "截止列应有常驻容器"
        assert w.findChild(QtWidgets.QDateEdit) is not None, \
            "截止列容器内应有 QDateEdit"
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
    """文本类编辑器 QSS 使用 todo_editor_border / todo_editor_border_hover 令牌。

    类别/优先级/状态三列是可改标签（实色胶囊），不走编辑框外观，另见
    test_option_columns_use_solid_badge_qss。
    """
    from core.theme.tokens import theme_palette
    win, table, ids = _make_page_with_rows(1)
    try:
        p = theme_palette()
        border = p["todo_editor_border"]
        hover = p["todo_editor_border_hover"]
        for col in (tn.COL_TITLE, tn.COL_CONTENT, tn.COL_DUE):
            w = table.cellWidget(0, col)
            assert w is not None, f"col {col} 应有常驻编辑器"
            if not isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit,
                                  QtWidgets.QDateEdit)):
                # 截止列是「容器 + 只读 QDateEdit + 清除按钮」，取容器内的日期控件
                w = w.findChild(QtWidgets.QDateEdit)
            qss = w.styleSheet()
            assert border in qss, f"col {col} QSS 应含 todo_editor_border 值 {border}"
            assert hover in qss, f"col {col} QSS 应含 todo_editor_border_hover 值 {hover}"
    finally:
        _cleanup(ids)


def test_option_columns_use_transparent_overlay_when_unfocused():
    """类别/优先级/状态 恢复旧观感：未聚焦时控件完全隐形。

    控件不再自绘胶囊，而是把背景/边框/内边距/下拉箭头/文字全部让出，
    由 delegate 画贴文字的彩色胶囊；聚焦时才临时显示为可见编辑器（防盲打）。
    """
    from core.theme.tokens import theme_palette
    from modules.todo_notes.constants import badge_overlay_qss

    win, table, ids = _make_page_with_rows(1)
    try:
        tn.update_todo(ids[0], category="工作", priority=2)
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        p = theme_palette()
        expected = badge_overlay_qss()
        for col in (tn.COL_CATEGORY, tn.COL_PRIORITY, tn.COL_STATUS):
            w = table.cellWidget(0, col)
            assert w is not None, f"col {col} 应有常驻编辑器"
            assert not w.hasFocus(), f"col {col} 初始不应处于聚焦态"
            qss = w.styleSheet()
            assert qss == expected, f"col {col} 未聚焦时应使用隐形 overlay QSS"
            assert "QComboBox::drop-down" in qss, f"col {col} 应隐藏下拉箭头"
            assert "width: 0" in qss, f"col {col} 箭头区域应压成 0 宽"
            assert "background: transparent" in qss, \
                f"col {col} 不应自绘底色（胶囊由 delegate 绘制）"
            assert "color: transparent" in qss, \
                f"col {col} 文字应由 delegate 绘制（避免与胶囊错位重影）"
            assert "QComboBox QAbstractItemView" in qss, f"col {col} 缺少弹窗规则"
            assert p["qss_menu_bg"] in qss, f"col {col} 弹窗底色应来自 qss_menu_bg"
            assert p["text_primary"] in qss, f"col {col} 弹窗文字应来自 text_primary"
    finally:
        _cleanup(ids)


def test_badge_edit_qss_shows_editor_while_focused():
    """聚焦（准备手输/选择）时临时显示为可见编辑器，避免盲打。"""
    from core.theme.tokens import theme_palette
    from modules.todo_notes.constants import badge_edit_qss

    p = theme_palette()
    qss = badge_edit_qss(p["todo_option_palette"][0])
    assert p["todo_editor_bg"] in qss, "编辑态应使用编辑器底色"
    assert p["todo_editor_border"] in qss, "编辑态应使用编辑器边框"
    assert "QComboBox::drop-down" in qss, "编辑态也保持无箭头（旧观感）"
    assert "QComboBox QAbstractItemView" in qss, "编辑态同样需要弹窗规则"


def test_combo_popup_qss_declares_readable_colors():
    """下拉弹窗必须有显式底色/文字色。

    QComboBox 的 background 会被 Qt 推导成弹窗 view 的底色，不显式指定时
    会退化成黑底 + 近不可见文字（用户报告「背景都是黑色的和字完全一致」）。
    """
    from core.theme.tokens import theme_palette
    win, table, ids = _make_page_with_rows(1)
    try:
        p = theme_palette()
        for col in (tn.COL_CATEGORY, tn.COL_PRIORITY, tn.COL_STATUS):
            w = table.cellWidget(0, col)
            assert w is not None, f"col {col} 应有常驻编辑器"
            qss = w.styleSheet()
            assert "QComboBox QAbstractItemView" in qss, f"col {col} 缺少弹窗规则"
            assert p["qss_menu_bg"] in qss, f"col {col} 弹窗底色应来自 qss_menu_bg"
            assert p["text_primary"] in qss, f"col {col} 弹窗文字应来自 text_primary"
            assert p["qss_menu_sel_bg"] in qss, f"col {col} 弹窗选中底色应来自 qss_menu_sel_bg"
    finally:
        _cleanup(ids)


# 说明：下拉弹窗的像素级验证放在离屏探针
# `.omo/evidence/todo-notes-bugs/diag_popup_pixels.py`（先 apply_global_stylesheet
# 再抓弹窗像素：修复前为纯黑，修复后可读）。不在测试内做，是因为会话中期对整个
# QApplication 重设样式表会在前面测试残留的控件上触发原生崩溃
# （Windows fatal exception: access violation），无法稳定跑在完整套件里。


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

        def _expected(t):
            return tn.content_row_height(
                t, table.font(), table.columnWidth(tn.COL_CONTENT))

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


def test_single_line_option_widgets_fit_row():
    """单行行高下，胶囊列控件自身最小高度不得超过行高（否则胶囊被裁）。

    历史回归：给 combo 加 margin/padding 后其 minimumSizeHint 变成 42px，
    而单行行高只有 40px → 胶囊下部被截断。
    """
    win, table, ids = _make_page_with_rows(1)
    try:
        for col in (tn.COL_CATEGORY, tn.COL_PRIORITY, tn.COL_STATUS, tn.COL_DUE):
            w = table.cellWidget(0, col)
            assert w is not None, f"col {col} 应有常驻编辑器"
            need = w.minimumSizeHint().height()
            assert need <= table.rowHeight(0), \
                f"col {col} 最小高度 {need} 超过行高 {table.rowHeight(0)}，会被裁断"
    finally:
        _cleanup(ids)


def test_content_viewport_double_click_opens_detail(monkeypatch):
    """内容列的双击落在 QPlainTextEdit 的内部 viewport 上，也必须能进详情页。

    历史回归：_DblClickFilter 只装在控件外层，而 QPlainTextEdit 把双击投递给
    自己的 viewport 子控件，导致「内容区域双击还是无法进入详情页」。
    """
    from PySide6.QtTest import QTest
    from modules.todo_notes import page_widget as pw

    opened = []

    class _FakeDialog:
        def __init__(self, parent=None, todo=None):
            opened.append(todo)

        def exec(self):
            return 0

        def get_data(self):
            return {}

    monkeypatch.setattr(pw, "_TodoEditDialog", _FakeDialog)
    win, table, ids = _make_page_with_rows(1)
    try:
        ed = table.cellWidget(0, tn.COL_CONTENT)
        assert isinstance(ed, QtWidgets.QPlainTextEdit)
        QTest.mouseDClick(ed.viewport(), QtCore.Qt.LeftButton,
                          pos=ed.viewport().rect().center())
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert opened, "双击内容编辑器内部 viewport 应打开详情页"
    finally:
        _cleanup(ids)


def test_due_date_readonly_with_clear_button():
    """截止日期不允许直接手输：内部 lineEdit 只读 + 无上下箭头；清除键默认隐藏
    不占位、悬浮单元格才出现（贴右）、离开后隐藏；点清除按钮回到「无」。"""
    from modules.todo_store import get_todos

    win, table, ids = _make_page_with_rows(1)
    try:
        tn.update_todo(ids[0], due_date="2030-05-06")
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        holder = table.cellWidget(0, tn.COL_DUE)
        assert holder is not None, "截止列应有常驻控件"
        de = holder.findChild(QtWidgets.QDateEdit)
        assert de is not None, "截止列应包含日期控件"
        assert de.lineEdit().isReadOnly(), "截止日期不应支持直接手输（防误填默认日期）"
        assert de.buttonSymbols() == QtWidgets.QAbstractSpinBox.NoButtons, \
            "截止日期不应显示上下箭头（点击会误改日期）"
        btn = holder.findChild(QtWidgets.QWidget, "todo_due_clear")
        assert btn is not None, "截止列应有清除按钮"
        # 默认隐藏不占位：日期控件 stretch=1 吃满 holder 宽度（视觉贴右）
        assert not btn.isVisible(), "清除键默认应隐藏（不占位）"
        assert de.width() >= holder.width() - 1, \
            f"隐藏时日期控件应占满 holder（{de.width()} vs {holder.width()}）"
        # 悬浮进入单元格 -> 清除键出现且贴右
        QtWidgets.QApplication.sendEvent(
            holder, QtCore.QEvent(QtCore.QEvent.Enter))
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert btn.isVisible(), "悬浮进入截止单元格后清除键应出现"
        assert btn.geometry().right() >= de.geometry().right(), \
            "清除键应位于日期控件右侧（贴右）"
        assert btn.geometry().right() >= holder.width() - 1, \
            "清除键右边缘应贴住单元格右边缘"
        # 悬浮到按钮本身（子控件）不得导致隐藏（防抖/防闪烁）
        QtGui.QCursor.setPos(btn.mapToGlobal(btn.rect().center()))
        QtWidgets.QApplication.sendEvent(
            holder, QtCore.QEvent(QtCore.QEvent.Leave))
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert btn.isVisible(), "悬浮在清除键上时不得隐藏（防闪烁）"
        # 点击清除 -> 回到「无」+ DB 清空
        btn.click()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert table.item(0, tn.COL_DUE).text() == "", "清除后单元格应回到「无」"
        row = next(t for t in get_todos() if t["id"] == ids[0])
        assert not row["due_date"], "清除后 DB 的 due_date 应为空"
        # 离开单元格 -> 清除键隐藏
        QtGui.QCursor.setPos(win.mapToGlobal(QtCore.QPoint(0, 0)))
        QtWidgets.QApplication.sendEvent(
            holder, QtCore.QEvent(QtCore.QEvent.Leave))
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert not btn.isVisible(), "离开截止单元格后清除键应隐藏"
    finally:
        _cleanup(ids)


def test_due_date_click_opens_calendar_popup():
    """点击截止日期控件（日历箭头）应弹出日历，供用户选择日期。

    这是用户要求「截止日期不支持直接编辑，需要点击日期控件选择」的可执行契约：
    若把整个 QDateEdit 设为 readOnly，日历就再也弹不出来（实测），因此只让
    内部 lineEdit 只读，而控件本身保持可点击。
    """
    win, table, ids = _make_page_with_rows(1)
    try:
        tn.update_todo(ids[0], due_date="2030-05-06")
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        holder = table.cellWidget(0, tn.COL_DUE)
        de = holder.findChild(QtWidgets.QDateEdit)
        assert de is not None
        cal = de.calendarWidget()
        assert cal is not None, "日期控件应带日历弹窗"
        QTest.mouseClick(de, QtCore.Qt.LeftButton,
                         pos=QtCore.QPoint(de.width() - 8, de.height() // 2))
        for _ in range(8):
            QtWidgets.QApplication.processEvents()
        assert cal.isVisible(), "点击日期控件应弹出日历（否则无法选择日期）"
        cal.hide()
    finally:
        _cleanup(ids)


def test_due_date_edit_does_not_autofill_on_click():
    """点击日期控件本身不应改动日期（只读，只能通过日历选择）。"""
    from modules.todo_store import get_todos

    win, table, ids = _make_page_with_rows(1)
    try:
        le = _search_input(win)
        le.setText("__always_on"); le.returnPressed.emit()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        holder = table.cellWidget(0, tn.COL_DUE)
        de = holder.findChild(QtWidgets.QDateEdit)
        assert de is not None
        before = de.date()
        de.setFocus()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert de.date() == before, "聚焦不应改动日期"
        # 手输也不应生效（lineEdit 只读）
        before_text = de.text()
        QTest.keyClicks(de.lineEdit(), "1999")
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert de.text() == before_text, "截止日期不应支持直接手输"
        assert de.date() == before, "手输不应改动日期"
        row = next(t for t in get_todos() if t["id"] == ids[0])
        assert not row["due_date"], "未选择日期时 DB 应保持空"
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


def test_content_edit_persists_and_resets_to_todo():
    """内容列直接编辑：立即更新单元格/DB，并把状态重置回「待办」（done=0）。

    历史回归：内容编辑器是 QPlainTextEdit，其 textChanged() 是 0 参信号，
    而 page_widget 的连接 lambda 声明了 1 个位置参数 _t —— 每次按键都抛
    TypeError: missing 1 required positional argument: '_t'（data/logs/yzplan.log
    累计 655 条），编辑完全不落库。修复后：单元格文本即时更新、DB content
    同步、status_id 回到「待办」且 done=0、状态列文本与常驻下拉一致。
    """
    win, table, ids = _make_page_with_rows(1)
    try:
        # 前置：把该行置为「已完成」（done=1），验证内容编辑会重置回「待办」
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
        assert todos[ids[0]]["done"] == 1, "前置：行应处于已完成状态"

        # 在内容编辑器里输入新内容（QPlainTextEdit.textChanged 是 0 参信号）
        ed = table.cellWidget(0, tn.COL_CONTENT)
        assert isinstance(ed, QtWidgets.QPlainTextEdit)
        ed.setPlainText("新内容")
        for _ in range(5):
            QtWidgets.QApplication.processEvents()

        # 单元格文本立即更新
        assert table.item(0, tn.COL_CONTENT).text() == "新内容", \
            "内容单元格应立即反映编辑"
        # DB 同步：content 更新、done 归零、status_id 回到「待办」
        todos = {t["id"]: t for t in _ts.get_todos()}
        assert todos[ids[0]]["content"] == "新内容", "DB content 应同步"
        assert todos[ids[0]]["done"] == 0, "内容编辑应把 done 重置为 0"
        todo_sid = statuses["待办"]
        assert todos[ids[0]]["status_id"] == todo_sid, \
            "内容编辑应把 status_id 重置回「待办」"
        # 状态列文本与常驻下拉同步
        st_item = table.item(0, tn.COL_STATUS)
        assert st_item is not None
        assert st_item.text() == "待办", "状态列文本应回到「待办」"
        assert st_item.data(QtCore.Qt.UserRole) == todo_sid, \
            "状态列 UserRole 应回到待办 sid"
        st_combo = table.cellWidget(0, tn.COL_STATUS)
        assert st_combo is not None
        assert st_combo.currentData() == todo_sid, \
            "常驻状态下拉应同步到「待办」"
    finally:
        _cleanup(ids)


def test_option_cell_hover_does_not_focus_combo():
    """悬浮选项单元格不得把焦点交给常驻 combo（「悬浮吞字」回归）。

    根因：视口开启鼠标跟踪后，QAbstractItemView 会把键盘焦点交给悬浮格的
    cellWidget；WA_TransparentForMouseEvents 挡不住这个聚焦，一旦聚焦
    delegate 就切到编辑态 QSS 盖掉胶囊。修复 = 选项 combo 默认 NoFocus +
    鼠标穿透，仅单击激活路径临时恢复 StrongFocus。
    """
    win, table, ids = _make_page_with_rows(1)
    try:
        viewport = table.viewport()
        # 应用 QSS 的 :hover 规则会开启视口鼠标跟踪；测试必须复现同一条件
        # （否则 hover 聚焦路径根本不触发，断言会空转通过）。
        viewport.setMouseTracking(True)
        for col in (tn.COL_CATEGORY, tn.COL_PRIORITY, tn.COL_STATUS):
            ed = table.cellWidget(0, col)
            assert ed is not None, f"col {col} 应有常驻 combo"
            cell = table.visualRect(table.model().index(0, col))
            QTest.mouseMove(viewport, cell.center())
            for _ in range(5):
                QtWidgets.QApplication.processEvents()
            assert ed.hasFocus() is False, \
                f"col {col}: 悬浮后 combo 不应获得焦点（悬浮吞字）"
            assert ed.testAttribute(
                QtCore.Qt.WA_TransparentForMouseEvents) is True, \
                f"col {col}: 悬浮后 combo 应保持鼠标穿透"
            assert ed.focusPolicy() == QtCore.Qt.NoFocus, \
                f"col {col}: 悬浮后 combo 焦点策略应为 NoFocus"
    finally:
        _cleanup(ids)