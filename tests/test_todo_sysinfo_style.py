"""Task 5: todo_notes + sys_info 样式迁移护栏（令牌化）。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _qss_colors(qss):
    return set(re.findall(r"#[0-9a-fA-F]{6}", qss))


def test_priority_colors_theme_aware():
    """priority_colors() 返回主题感知的优先级色（0-3 全键）。"""
    from modules.todo_notes.constants import priority_colors
    try:
        _force_dark(True)
        dark = priority_colors()
        _force_dark(False)
        light = priority_colors()
        assert set(dark) == {0, 1, 2, 3}
        assert set(light) == {0, 1, 2, 3}
        assert any(dark[k] != light[k] for k in (0, 1, 2, 3))
    finally:
        _restore_dark()


def test_date_theme_qss_colors_from_palette():
    """日历 QSS 全部 #hex 色来自全局调色板（明暗两套）。"""
    from core.theme.tokens import theme_palette
    from modules.todo_notes.date_theme import _calendar_qss
    try:
        for dark in (True, False):
            _force_dark(dark)
            p = theme_palette()
            palette_hexes = {v for v in p.values()
                             if isinstance(v, str) and v.startswith("#")}
            qss = _calendar_qss(p)
            found = _qss_colors(qss)
            assert found, f"{'暗' if dark else '亮'}色日历 QSS 应包含颜色"
            assert found <= palette_hexes, \
                f"{'暗' if dark else '亮'}色日历 QSS 含非令牌色: {found - palette_hexes}"
    finally:
        _restore_dark()


def test_sysinfo_palette_from_global():
    """sys_info 编辑区色板来自全局令牌（无私有色板）。"""
    from core.theme.tokens import theme_palette
    from modules.sys_info_widget import _sysinfo_palette
    try:
        for dark in (True, False):
            _force_dark(dark)
            c = _sysinfo_palette()
            p = theme_palette()
            assert c["edit_bg"] == p["sysinfo_edit_bg"]
            assert c["edit_border"] == p["border"]
            assert c["text"] == p["text_primary"]
            assert c["dark"] is dark
    finally:
        _restore_dark()


def test_sysinfo_edit_min_height_from_sizing():
    """sys_info 编辑区最小高度来自 sizing() 令牌。"""
    from core.theme.tokens import sizing
    from modules.sys_info_widget import _make_edit
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    edit = _make_edit({"edit_bg": "#000000", "edit_border": "#000000",
                       "text": "#ffffff"})
    assert edit.minimumHeight() == sizing()["sysinfo_edit_min_height"]