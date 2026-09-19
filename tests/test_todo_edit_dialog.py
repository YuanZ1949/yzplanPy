"""todo 17：_TodoEditDialog 重做测试——全部属性编辑 + 状态改名即新建 + 颜色画板 + 内容重置。

覆盖：
- 弹窗包含标题/内容/类别/优先级/截止日期/状态/颜色全部控件
- 编辑已有条目时各控件回填当前值
- 修改状态并确定后 status_id 更新（done 随 is_done_like 同步）
- 输入新状态名即"改名即新建"
- 修改内容并确定后状态被重置为「待办」（与 todo 13 一致）
- 色块点击 → QColorDialog → set_status_color 持久化（含新状态名先建后设色）
- 弹窗源码无硬编码 hex/rgba 色值与手写 px 尺寸
- 弹窗确定后表格对应行已刷新（保存后表格与 DB 同步）
"""
import inspect
import re
import sys

import pytest

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

_, QtCore, QtGui, QtWidgets = import_qt()

from modules import todo_notes as tn
from modules import todo_store as _ts
from modules.todo_store import (
    add_status,
    add_todo,
    get_statuses,
    get_or_create_status,
    set_status_color,
    update_todo,
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


def _make_page_with_rows(n):
    """建页并插入 n 条测试便签，返回 (win, table, ids)。"""
    ids = [add_todo(f"__dlg_row{i}__", content="c") for i in range(n)]
    win, page = _make_page()
    table = _find_table(win)
    return win, table, ids


def _make_dialog(todo=None):
    _app()
    return tn._TodoEditDialog(todo=todo)


def _status_ids():
    statuses = get_statuses()
    return {
        "待办": next(s["id"] for s in statuses if s["name"] == "待办"),
        "已完成": next(s["id"] for s in statuses if s["name"] == "已完成"),
    }


def _raw_todo_row(tid):
    import sqlite3 as _sq

    conn = _sq.connect(_ts.DB_PATH)
    try:
        return conn.execute(
            "SELECT done, status_id FROM todo_notes WHERE id = ?", (tid,)
        ).fetchone()
    finally:
        conn.close()


def test_dialog_has_all_field_controls():
    """弹窗包含标题/内容/类别/优先级/截止日期/状态/颜色全部控件。"""
    dlg = _make_dialog()
    assert dlg.title_input is not None
    assert dlg.content_input is not None
    assert dlg.cat_combo is not None
    assert dlg.pri_combo is not None
    assert dlg.due_check is not None
    assert dlg.due_date is not None
    assert dlg.status_combo is not None
    assert dlg.color_btn is not None
    assert dlg.cat_color_btn is not None, "详情页类别行应有颜色色块"
    # 表格全部列都要能在详情页编辑：勾选（完成）与创建时间
    assert dlg.done_check is not None, "详情页应有「完成」勾选"
    assert dlg.created_at_edit is not None, "详情页应有「创建时间」"
    # 状态为可编辑下拉，选项来自 get_statuses() + 末尾「自定义…」哨兵
    assert dlg.status_combo.isEditable(), "状态应为可编辑下拉框"
    statuses = get_statuses()
    assert dlg.status_combo.count() == len(statuses) + 1, \
        "状态选项数应 == get_statuses() 数 + 哨兵"
    for s in statuses:
        assert dlg.status_combo.findData(s["id"]) >= 0, f"缺少状态 {s['name']}"
    assert dlg.status_combo.findData(tn.CUSTOM_OPTION_DATA) >= 0, \
        "状态下拉应含「自定义…」哨兵项"
    assert dlg.cat_combo.findData(tn.CUSTOM_OPTION_DATA) >= 0, \
        "类别下拉应含「自定义…」哨兵项"


def test_dialog_prefills_existing_todo():
    """编辑已有条目时各控件回填当前值。"""
    tid = add_todo("__dlg_prefill__", content="内容", priority=2,
                   category="工作", due_date="2026-12-31")
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        assert dlg.title_input.text() == "__dlg_prefill__"
        assert dlg.content_input.toPlainText() == "内容"
        assert dlg.pri_combo.currentData() == 2
        assert dlg.cat_combo.currentText() == "工作"
        assert dlg.due_check.isChecked()
        assert dlg.due_date.date().toString("yyyy-MM-dd") == "2026-12-31"
        assert dlg.status_combo.currentData() == todo["status_id"]
    finally:
        _ts.delete_todo(tid)


def test_status_change_saves_status_id():
    """修改状态并确定后该条目 status_id 更新（done 随 is_done_like 同步）。"""
    tid = add_todo("__dlg_status__", content="c")
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        sids = _status_ids()
        idx = dlg.status_combo.findData(sids["已完成"])
        dlg.status_combo.setCurrentIndex(idx)
        data = dlg.get_data()
        assert data["status_id"] == sids["已完成"]
        update_todo(tid, **data)
        todos = {t["id"]: t for t in _ts.get_todos()}
        assert todos[tid]["status_id"] == sids["已完成"]
        assert todos[tid]["done"] == 1  # 已完成 is_done_like=1 → done=1
    finally:
        _ts.delete_todo(tid)


def test_new_status_name_creates_status():
    """输入新状态名（改名即新建）→ get_data 返回新建状态 id。"""
    tid = add_todo("__dlg_new_status__", content="c")
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        dlg.status_combo.setCurrentText("进行中")
        data = dlg.get_data()
        sid = data["status_id"]
        assert sid is not None
        statuses = {s["id"]: s for s in get_statuses()}
        assert statuses[sid]["name"] == "进行中"
    finally:
        _ts.delete_todo(tid)


def test_content_change_resets_status_to_todo():
    """修改内容并确定后状态被重置为「待办」（与 todo 13 一致）。"""
    tid = add_todo("__dlg_content_reset__", content="orig")
    try:
        sids = _status_ids()
        update_todo(tid, done=1)  # 先置为已完成
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        dlg.content_input.setPlainText("new content")
        data = dlg.get_data()
        # 模拟 on_edit 的保存流程（先保存弹窗数据，再按内容变更重置状态）
        update_todo(tid, **data)
        tn._maybe_reset_done_on_content_change(tid, todo["content"], data["content"])
        done, status_id = _raw_todo_row(tid)
        assert done == 0
        assert status_id == sids["待办"]
    finally:
        _ts.delete_todo(tid)


def test_color_swatch_persists_status_color(monkeypatch):
    """点击色块 → QColorDialog 选色 → 持久化到当前状态。"""
    _app()
    sid = add_status("进行中")
    try:
        dlg = _make_dialog()
        dlg.status_combo.setCurrentText("进行中")
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#123456"))
        dlg.color_btn.click()
        st = next(s for s in get_statuses() if s["id"] == sid)
        assert st["color"] == "#123456"
        assert dlg.color_btn._swatch_color == "#123456"
    finally:
        _ts.delete_status(sid)


def test_color_swatch_creates_new_status(monkeypatch):
    """新状态名上点色块 → 先创建状态再持久化颜色（改名即新建）。"""
    _app()
    dlg = _make_dialog()
    dlg.status_combo.setCurrentText("全新状态")
    monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                        lambda *a, **k: QtGui.QColor("#abcdef"))
    dlg.color_btn.click()
    st = next(s for s in get_statuses() if s["name"] == "全新状态")
    assert st["color"] == "#abcdef"
    _ts.delete_status(st["id"])


def test_dialog_no_hardcoded_colors_or_px():
    """弹窗源码不出现硬编码 hex/rgba 色值与手写 px 尺寸。"""
    src = inspect.getsource(tn._TodoEditDialog)
    # 无 hex 字面量（#rrggbb）
    assert not re.search(r"#[0-9a-fA-F]{6}", src), "弹窗源码不应含硬编码 hex 色值"
    # 无 rgba/rgb 字面量
    assert not re.search(r"rgba?\s*\(\s*\d", src), "弹窗源码不应含硬编码 rgba/rgb 色值"
    # 无 setFixedHeight(数字) / setMinimumHeight(数字)
    assert not re.search(r"set(?:Fixed|Minimum)Height\(\s*\d+", src), "弹窗源码不应含手写固定高度"
    # 无 QSS 内数字 px 尺寸字面量
    assert not re.search(
        r"(?:padding|margin|width|height|border-radius|font-size|line-height):\s*\d+px", src
    ), "弹窗源码不应含手写 px 尺寸"


def test_dialog_save_refreshes_table(monkeypatch):
    """弹窗确定后表格对应行已刷新（保存后表格与 DB 同步）。"""
    win, table, ids = _make_page_with_rows(1)
    try:
        class _FakeDialog:
            def __init__(self, *a, **k):
                self._todo = a[1] if len(a) > 1 else None

            def exec(self):
                return QtWidgets.QDialog.Accepted

            def get_data(self):
                return {
                    "title": "__dlg_edited__",
                    "content": "c",
                    "priority": 1,
                    "category": "",
                    "due_date": None,
                    "status_id": self._todo["status_id"] if self._todo else None,
                }

        # page_widget 模块内引用的是其命名空间里的 _TodoEditDialog
        import modules.todo_notes.page_widget as pw

        monkeypatch.setattr(pw, "_TodoEditDialog", _FakeDialog)
        table.selectRow(0)
        table.cellDoubleClicked.emit(0, tn.COL_TITLE)
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        # 表格已刷新：标题列显示新值
        assert table.item(0, tn.COL_TITLE).text() == "__dlg_edited__"
        # DB 同步
        todos = {t["id"]: t for t in tn.get_todos()}
        assert todos[ids[0]]["title"] == "__dlg_edited__"
    finally:
        for i in ids:
            tn.delete_todo(i)


def test_dialog_covers_all_table_columns():
    """详情页覆盖表格全部列：完成勾选 + 创建时间也可编辑。"""
    tid = add_todo("__dlg_all_cols__", content="c")
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        assert dlg.done_check.isChecked() is False
        assert dlg.created_at_edit.dateTime().toString("yyyy-MM-dd HH:mm") \
            == todo["created_at"][:16], "创建时间应回填当前值"
        # 勾选完成 → 状态同步为已完成类，落库 done=1
        dlg.done_check.setChecked(True)
        data = dlg.get_data()
        statuses = {s["id"]: s for s in get_statuses()}
        assert statuses[data["status_id"]]["is_done_like"] == 1, \
            "勾选完成应把状态同步为已完成类（done 由 status 推导）"
        assert data["done"] == 1
        update_todo(tid, **data)
        done, status_id = _raw_todo_row(tid)
        assert done == 1 and status_id == data["status_id"]
        # 创建时间可编辑并落库
        dlg.created_at_edit.setDateTime(QtCore.QDateTime(2020, 1, 2, 3, 4, 0))
        data = dlg.get_data()
        assert data["created_at"].startswith("2020-01-02 03:04")
        update_todo(tid, **data)
        todos = {t["id"]: t for t in _ts.get_todos()}
        assert todos[tid]["created_at"].startswith("2020-01-02 03:04"), \
            "创建时间修改应持久化"
    finally:
        _ts.delete_todo(tid)


def test_dialog_done_check_follows_status_selection():
    """状态选到已完成类 → 完成勾选自动勾上；取消勾选 → 状态回到未完成类。"""
    tid = add_todo("__dlg_done_sync__", content="c")
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        sids = _status_ids()
        dlg.status_combo.setCurrentIndex(dlg.status_combo.findData(sids["已完成"]))
        assert dlg.done_check.isChecked() is True, "选中已完成状态应自动勾选完成"
        dlg.done_check.setChecked(False)
        statuses = {s["id"]: s for s in get_statuses()}
        assert statuses[dlg.status_combo.currentData()]["is_done_like"] == 0, \
            "取消勾选完成应把状态切回未完成类"
    finally:
        _ts.delete_todo(tid)


def _show_dialog(dlg):
    """show + processEvents：布局激活后 viewport 才 laid-out，滚动条 maximum 才可信。"""
    dlg._dlg.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()


def _content_chrome(ci):
    """内容框 chrome：上下 contentsMargins + 2×文档边距。"""
    margins = ci.contentsMargins()
    return margins.top() + margins.bottom() + 2 * ci.document().documentMargin()


def test_content_box_fits_document_height():
    """3 行内容 → 内容框无内部滚动条，高度 ≈ 文本高度 + chrome（不预留空行）。"""
    dlg = _make_dialog()
    dlg.content_input.setPlainText("第一行\n第二行\n第三行")
    _show_dialog(dlg)
    try:
        ci = dlg.content_input
        assert ci.verticalScrollBar().maximum() == 0, "3 行内容不应出现内部滚动条"
        fm = QtGui.QFontMetrics(ci.font())
        text_h = ci.document().size().height() * fm.lineSpacing()
        chrome = _content_chrome(ci)
        assert abs(ci.height() - text_h) <= chrome + 2 * ci.frameWidth() + 2, \
            f"内容框高度 {ci.height()} 应≈文本 {text_h:.0f} + chrome {chrome}"
    finally:
        dlg._dlg.close()


def test_dialog_grows_with_content():
    """20 行内容 → 弹窗比 3 行时更高（内容框自适应驱动弹窗长高）。"""
    dlg = _make_dialog()
    dlg.content_input.setPlainText("a\nb\nc")
    _show_dialog(dlg)
    try:
        h3 = dlg._dlg.height()
        dlg.content_input.setPlainText("\n".join(f"line {i}" for i in range(20)))
        for _ in range(10):
            QtWidgets.QApplication.processEvents()
        h20 = dlg._dlg.height()
        assert h20 > h3, f"20 行时弹窗高 {h20} 应大于 3 行时 {h3}"
        assert dlg.content_input.verticalScrollBar().maximum() == 0, \
            "20 行内容仍不应出现内部滚动条"
    finally:
        dlg._dlg.close()


def test_content_box_caps_at_max_height():
    """60 行内容 → 内容框钳制在上限、出现内部滚动条、弹窗不超过屏幕。"""
    dlg = _make_dialog()
    dlg.content_input.setPlainText("\n".join(f"line {i}" for i in range(60)))
    _show_dialog(dlg)
    try:
        ci = dlg.content_input
        cap = sizing()["todo_dialog_content_max_height"]
        assert ci.height() == cap, f"60 行内容框应钳制在上限 {cap}"
        assert ci.verticalScrollBar().maximum() > 0, "超上限内容应出现内部滚动条"
        avail_h = dlg._dlg.screen().availableGeometry().height()
        assert dlg._dlg.height() <= avail_h, \
            f"弹窗高 {dlg._dlg.height()} 不应超过屏幕可用高 {avail_h}"
    finally:
        dlg._dlg.close()


def test_empty_content_is_single_line_height():
    """空内容 → 高度 == 单行高度 + chrome（不是 80px 下限）。"""
    dlg = _make_dialog()
    _show_dialog(dlg)
    try:
        ci = dlg.content_input
        fm = QtGui.QFontMetrics(ci.font())
        chrome = _content_chrome(ci)
        single = fm.lineSpacing() + chrome
        assert abs(ci.height() - single) <= 2 * ci.frameWidth() + 2, \
            f"空内容高度 {ci.height()} 应≈单行 {single:.0f}（而非 80px 下限）"
        assert ci.height() < 80, "空内容不应再受 80px 最小高度限制"
    finally:
        dlg._dlg.close()


def test_content_box_height_includes_theme_qss_padding():
    """主题 QSS 已应用时，空内容高度必须按 polish 后的 chrome 计算。

    回归：_fit_content_height 在构造期（polish 前）量 contentsMargins，主题 QSS
    的 QPlainTextEdit padding 尚未生效 → chrome 偏小 10px → 内容框矮一行；
    全量套件中 test_theme_borders.py 残留的浅色 QSS 会稳定复现该缺陷。
    """
    app = _app()
    saved = app.styleSheet()
    from core.theme.qss_light import _apply_light_sheet

    _apply_light_sheet(False)
    try:
        dlg = _make_dialog()
        _show_dialog(dlg)
        try:
            ci = dlg.content_input
            fm = QtGui.QFontMetrics(ci.font())
            single = fm.lineSpacing() + _content_chrome(ci)
            assert abs(ci.height() - single) <= 2 * ci.frameWidth() + 2, \
                f"主题 QSS 下空内容高度 {ci.height()} 应≈单行 {single:.0f}"
        finally:
            dlg._dlg.close()
    finally:
        app.setStyleSheet(saved)


def test_content_box_fits_wrapped_content():
    """单行长文本自动折行 → show 后内容框完整容纳折行、无内部滚动条。

    回归：构造期文档尚未按最终宽度布局，doc.size().height() 只返回段落数，
    单段长文本（1 段但折行成多行）会算出偏矮的内容框 → 出现内部滚动条、
    末行文字被截断。
    """
    dlg = _make_dialog()
    dlg.content_input.setPlainText("这是一段会被自动折行的长内容" * 6)
    _show_dialog(dlg)
    try:
        ci = dlg.content_input
        fm = QtGui.QFontMetrics(ci.font())
        lines = ci.document().size().height()
        assert lines > 1, "前置条件：该文本应折行成多行"
        assert ci.verticalScrollBar().maximum() == 0, \
            f"折行 {lines:.0f} 行内容不应出现内部滚动条"
        needed = lines * fm.lineSpacing()
        assert ci.viewport().height() + 2 >= needed, \
            f"视口高 {ci.viewport().height()} 应容纳折行文本 {needed:.0f}"
    finally:
        dlg._dlg.close()


def test_content_box_fits_wrapped_todo_on_open():
    """打开已有长折行内容的待办 → 内容框完整显示（无内部滚动条）。"""
    tid = add_todo("__dlg_wrap__", content="很长的一段待办内容需要自动折行显示" * 5)
    dlg = None
    try:
        todo = next(t for t in _ts.get_todos() if t["id"] == tid)
        dlg = _make_dialog(todo=todo)
        _show_dialog(dlg)
        ci = dlg.content_input
        assert ci.verticalScrollBar().maximum() == 0, \
            "打开长折行内容不应出现内部滚动条"
    finally:
        _ts.delete_todo(tid)
        if dlg is not None:
            dlg._dlg.close()


def test_combo_arrow_is_token_derived_and_visible():
    """make_combo 下拉箭头：非零、令牌派生（border-top == combo_arrow_h）。

    回归：详情弹窗下拉箭头曾渲染成 1px 小点——箭头必须由 sizing() 的
    combo_arrow_h 令牌驱动，且高度非零，才读得出「向下箭头」。
    """
    from ui.widgets import make_combo

    sz = sizing()
    cb = make_combo(["a", "b"])
    qss = cb.styleSheet()
    m = re.search(r"QComboBox::down-arrow\s*\{[^}]*border-top:\s*(\d+)px", qss)
    assert m, f"down-arrow 规则应含 border-top，实际 QSS: {qss}"
    assert int(m.group(1)) > 0, "down-arrow border-top 应为非零"
    assert int(m.group(1)) == sz["combo_arrow_h"], \
        f"border-top {m.group(1)}px 应等于 combo_arrow_h 令牌 {sz['combo_arrow_h']}"


def test_badge_qss_does_not_zero_down_arrow():
    """badge QSS 不再把下拉箭头压成 0 宽/0 高（详情弹窗箭头可见）。

    回归：badge_overlay_qss/badge_edit_qss 曾用 `width:0;height:0` 归零箭头，
    使详情弹窗下拉读作小点。现在任何 badge QSS 的 down-arrow 规则都不得
    再出现 width:0 / height:0。
    """
    from modules.todo_notes.qss_builders import badge_edit_qss, badge_overlay_qss

    for qss in (badge_overlay_qss(), badge_edit_qss()):
        assert not re.search(
            r"QComboBox::down-arrow\s*\{[^}]*width:\s*0[^}]*\}", qss), \
            f"badge QSS 不应再 width:0 归零箭头: {qss}"
        assert not re.search(
            r"QComboBox::down-arrow\s*\{[^}]*height:\s*0[^}]*\}", qss), \
            f"badge QSS 不应再 height:0 归零箭头: {qss}"


def test_dialog_combos_align():
    """详情弹窗三个下拉框等宽、表单标签右对齐（QFormLayout 对齐契约）。

    与标签管理两列对齐同一模式：同功能控件共享位置与尺寸。
    """
    dlg = _make_dialog()
    _show_dialog(dlg)
    try:
        widths = {dlg.cat_combo.width(), dlg.pri_combo.width(),
                  dlg.status_combo.width()}
        assert len(widths) == 1, \
            f"类别/优先级/状态下拉应等宽，实际: {widths}"
        labels = [l for l in dlg._dlg.findChildren(QtWidgets.QLabel) if l.text()]
        assert labels, "弹窗应有表单标签"
        right_edges = {l.geometry().right() for l in labels}
        assert len(right_edges) == 1, \
            f"表单标签应右对齐，实际右缘: {right_edges}"
    finally:
        dlg._dlg.close()