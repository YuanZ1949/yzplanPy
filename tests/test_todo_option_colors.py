"""todo 选项多颜色（todo 16）测试：存储层 + 颜色解析 + 标签管理对话框 + 右键改色。

TDD：先写失败测试，再实现。
"""
import sys

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from conftest import _force_dark, _restore_dark

from modules.todo_store import (
    add_status, add_todo, get_categories, get_statuses, set_status_color,
    _get_conn, _migrate_statuses,
    get_option_color, set_option_color, get_all_option_colors, delete_option_color,
)
from modules.todo_notes.constants import (
    COLOR_COL_CATEGORY, COLOR_COL_PRIORITY, COLOR_COL_STATUS,
    category_color, priority_color, status_color,
)
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


# ---------------------------------------------------------------------------
# 1. 存储层：todo_option_colors 表
# ---------------------------------------------------------------------------

class TestOptionColorStore:
    def test_get_option_color_none_when_unset(self):
        """未设置时返回 None。"""
        assert get_option_color("priority", "1") is None

    def test_set_and_get_option_color(self):
        """set_option_color 后可读回。"""
        set_option_color("priority", "1", "#123456")
        assert get_option_color("priority", "1") == "#123456"

    def test_set_option_color_upsert(self):
        """重复 set 同一选项覆盖旧值（不产生重复行）。"""
        set_option_color("priority", "1", "#111111")
        set_option_color("priority", "1", "#222222")
        assert get_option_color("priority", "1") == "#222222"
        conn = _get_conn()
        n = conn.execute(
            "SELECT COUNT(*) FROM todo_option_colors WHERE column=? AND option_value=?",
            ("priority", "1"),
        ).fetchone()[0]
        conn.close()
        assert n == 1

    def test_get_all_option_colors(self):
        """get_all_option_colors 返回 {(column, value): color}。"""
        set_option_color("priority", "1", "#111111")
        set_option_color("category", "工作", "#222222")
        assert get_all_option_colors() == {
            ("priority", "1"): "#111111",
            ("category", "工作"): "#222222",
        }

    def test_delete_option_color(self):
        """delete_option_color 删除记录。"""
        set_option_color("priority", "1", "#111111")
        delete_option_color("priority", "1")
        assert get_option_color("priority", "1") is None

    def test_option_colors_table_created_by_migration(self):
        """迁移建表：todo_option_colors 含 column/option_value/color 三列。"""
        _migrate_statuses()
        conn = _get_conn()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(todo_option_colors)").fetchall()]
        conn.close()
        assert "column" in cols
        assert "option_value" in cols
        assert "color" in cols


# ---------------------------------------------------------------------------
# 2. 颜色解析：存储色优先，回落默认
# ---------------------------------------------------------------------------

class TestPriorityColor:
    def test_stored_color_wins(self):
        """优先级存储色优先于令牌默认色。"""
        set_option_color(COLOR_COL_PRIORITY, "1", "#123456")
        assert priority_color(1) == "#123456"

    def test_default_fallback_uses_priority_colors(self):
        """未存储时回落 priority_colors() 令牌色（默认值语义不变）。"""
        from modules.todo_notes.constants import priority_colors
        pc = priority_colors()
        assert priority_color(1) == pc[1]

    def test_unknown_priority_falls_back_to_first(self):
        """未知优先级值回落第一个令牌色。"""
        from modules.todo_notes.constants import priority_colors
        pc = priority_colors()
        assert priority_color(99) == pc[0]


class TestCategoryColor:
    def test_stored_color_wins(self):
        """类别存储色优先。"""
        add_todo("t", category="工作")
        set_option_color(COLOR_COL_CATEGORY, "工作", "#123456")
        assert category_color("工作") == "#123456"

    def test_default_fallback_cycles_palette(self):
        """未存储时按类别序号从 todo_option_palette 循环取色。"""
        from core.theme.tokens import theme_palette
        add_todo("a", category="A类")
        add_todo("b", category="B类")
        p = theme_palette()
        palette = p["todo_option_palette"]
        assert category_color("A类") == palette[0]
        assert category_color("B类") == palette[1]

    def test_same_option_value_different_color_per_column(self):
        """同名选项在不同列可有不同色（各列独立）。"""
        set_option_color(COLOR_COL_PRIORITY, "1", "#111111")
        set_option_color(COLOR_COL_CATEGORY, "1", "#222222")
        assert priority_color(1) == "#111111"
        assert category_color("1") == "#222222"


class TestStatusDefaultColor:
    def test_sixth_status_gets_different_default_color(self):
        """新增第 6 个状态自动获得与第 1 个不同的默认色（按序号循环）。"""
        _migrate_statuses()
        first = next(s for s in get_statuses() if s["name"] == "待办")
        for name in ("S3", "S4", "S5", "S6"):
            add_status(name)
        statuses = get_statuses()
        sixth = next(s for s in statuses if s["name"] == "S6")
        assert status_color(first) != status_color(sixth)

    def test_status_stored_color_wins(self):
        """set_status_color 后 status_color 返回存储色。"""
        _migrate_statuses()
        sid = add_status("测试色")
        set_status_color(sid, "#123456")
        st = next(s for s in get_statuses() if s["id"] == sid)
        assert status_color(st) == "#123456"


# ---------------------------------------------------------------------------
# 3. 颜色不区分主题（存储色跨暗/亮不变）
# ---------------------------------------------------------------------------

class TestThemeIndependence:
    def test_stored_option_color_unchanged_across_themes(self):
        """优先级存储色在暗/亮主题切换后不变。"""
        set_option_color(COLOR_COL_PRIORITY, "1", "#123456")
        try:
            _force_dark(True)
            c1 = priority_color(1)
            _force_dark(False)
            c2 = priority_color(1)
            assert c1 == c2 == "#123456"
        finally:
            _restore_dark()

    def test_stored_status_color_unchanged_across_themes(self):
        """状态存储色在暗/亮主题切换后不变。"""
        _migrate_statuses()
        sid = add_status("主题色")
        set_status_color(sid, "#654321")
        st = next(s for s in get_statuses() if s["id"] == sid)
        try:
            _force_dark(True)
            c1 = status_color(st)
            _force_dark(False)
            c2 = status_color(st)
            assert c1 == c2 == "#654321"
        finally:
            _restore_dark()


# ---------------------------------------------------------------------------
# 4. 标签管理对话框
# ---------------------------------------------------------------------------

class TestTagManagerDialog:
    def _make_dialog(self):
        _app()
        from modules.todo_notes.tag_manager import _TagManagerDialog
        return _TagManagerDialog()

    def test_lists_all_columns_options(self):
        """对话框列出状态/优先级/类别全部选项，且每个色块有颜色。"""
        _migrate_statuses()
        add_status("进行中")
        add_todo("t", category="工作")
        dlg = self._make_dialog()
        # 状态：待办/已完成/进行中 = 3
        assert len(dlg._status_rows) == 3
        # 优先级：低/中/高/紧急 = 4
        assert len(dlg._priority_rows) == 4
        # 类别：工作 = 1
        assert len(dlg._category_rows) == 1
        for sw, _ in dlg._status_rows + dlg._priority_rows + dlg._category_rows:
            assert getattr(sw, "_swatch_color", None)

    def test_swatch_click_persists_status_color(self, monkeypatch):
        """点击状态色块 → QColorDialog 选色 → 持久化到 todo_statuses.color。"""
        _migrate_statuses()
        sid = add_status("进行中")
        dlg = self._make_dialog()
        sw = next(sw for sw, s in dlg._status_rows if s == sid)
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#123456"))
        sw.click()
        st = next(s for s in get_statuses() if s["id"] == sid)
        assert st["color"] == "#123456"
        assert sw._swatch_color == "#123456"

    def test_swatch_click_persists_priority_color(self, monkeypatch):
        """点击优先级色块 → 持久化到 todo_option_colors。"""
        dlg = self._make_dialog()
        sw = next(sw for sw, v in dlg._priority_rows if v == 2)
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#abcdef"))
        sw.click()
        assert get_option_color(COLOR_COL_PRIORITY, "2") == "#abcdef"
        assert sw._swatch_color == "#abcdef"

    def test_swatch_click_persists_category_color(self, monkeypatch):
        """点击类别色块 → 持久化到 todo_option_colors。"""
        add_todo("t", category="工作")
        dlg = self._make_dialog()
        sw = next(sw for sw, c in dlg._category_rows if c == "工作")
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#fedcba"))
        sw.click()
        assert get_option_color(COLOR_COL_CATEGORY, "工作") == "#fedcba"
        assert sw._swatch_color == "#fedcba"


# ---------------------------------------------------------------------------
# 5. 右键改色入口
# ---------------------------------------------------------------------------

class TestRightClickColor:
    def test_context_menu_has_color_entry_for_option_columns(self):
        """选项列（状态/优先级/类别）右键菜单含「设置颜色」入口；非选项列无。"""
        _ensure_test_data()
        win, page = _make_page()
        table = _find_table(win)
        todo = tn.get_todos()[0]
        for col in (tn.COL_STATUS, tn.COL_PRIORITY, tn.COL_CATEGORY):
            menu, acts = tn._build_todo_menu(todo, col, 0)
            assert acts["color"] is not None, f"col {col} 应有改色入口"
            assert acts["color"].text() == "设置颜色..."
        menu2, acts2 = tn._build_todo_menu(todo, tn.COL_TITLE, 0)
        assert acts2["color"] is None

    def test_context_menu_has_rename_delete_entries_for_tag_columns(self):
        """状态/类别列右键菜单含「重命名」「删除该选项」入口；标题/优先级列无。"""
        _ensure_test_data()
        win, page = _make_page()
        table = _find_table(win)
        todo = tn.get_todos()[0]
        for col in (tn.COL_STATUS, tn.COL_CATEGORY):
            menu, acts = tn._build_todo_menu(todo, col, 0)
            assert acts["rename_opt"] is not None, f"col {col} 应有重命名入口"
            assert acts["rename_opt"].text() == "重命名"
            assert acts["delete_opt"] is not None, f"col {col} 应有删除入口"
            assert acts["delete_opt"].text() == "删除该选项"
        for col in (tn.COL_TITLE, tn.COL_PRIORITY):
            menu, acts = tn._build_todo_menu(todo, col, 0)
            assert acts["rename_opt"] is None, f"col {col} 不应有重命名入口"
            assert acts["delete_opt"] is None, f"col {col} 不应有删除入口"

    def test_pick_cell_color_persists_status(self, monkeypatch):
        """右键状态单元格选色 → 持久化并触发刷新。"""
        _ensure_test_data()
        win, page = _make_page()
        table = _find_table(win)
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#123456"))
        refreshed = []
        sid = table.item(0, tn.COL_STATUS).data(QtCore.Qt.UserRole)
        tn._pick_cell_color_for(table, 0, tn.COL_STATUS, lambda: refreshed.append(1))
        st = next(s for s in tn.get_statuses() if s["id"] == sid)
        assert st["color"] == "#123456"
        assert refreshed == [1]

    def test_pick_cell_color_persists_priority(self, monkeypatch):
        """右键优先级单元格选色 → 持久化到 todo_option_colors。"""
        _ensure_test_data()
        win, page = _make_page()
        table = _find_table(win)
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor("#abcdef"))
        refreshed = []
        val = table.item(0, tn.COL_PRIORITY).data(QtCore.Qt.UserRole)
        tn._pick_cell_color_for(table, 0, tn.COL_PRIORITY, lambda: refreshed.append(1))
        assert get_option_color(COLOR_COL_PRIORITY, str(val)) == "#abcdef"
        assert refreshed == [1]

    def test_pick_cell_color_cancel_does_nothing(self, monkeypatch):
        """取消选色（QColorDialog 返回无效色）不持久化、不刷新。"""
        _ensure_test_data()
        win, page = _make_page()
        table = _find_table(win)
        monkeypatch.setattr(QtWidgets.QColorDialog, "getColor",
                            lambda *a, **k: QtGui.QColor())
        refreshed = []
        sid = table.item(0, tn.COL_STATUS).data(QtCore.Qt.UserRole)
        tn._pick_cell_color_for(table, 0, tn.COL_STATUS, lambda: refreshed.append(1))
        st = next(s for s in tn.get_statuses() if s["id"] == sid)
        assert st["color"] is None
        assert refreshed == []