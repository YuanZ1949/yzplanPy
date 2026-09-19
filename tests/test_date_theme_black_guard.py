"""Task 12b: QCalendarWidget body opaque-black in LIGHT theme — regression guard.

Root cause (proven by task-12 audit + offscreen probe): the light
`_calendar_qss` (modules/todo_notes/date_theme.py:29-33) sets
selection-background-color / selection-color / color on QAbstractItemView but
NO `background` rule. Combined with the global QSS `QFrame{background:transparent}`,
QStyleSheetStyle resolves the view's Base palette role to rgba(0,0,0,255) in
light mode -> the whole calendar body renders opaque black (62,441 px in the
audit grab). Dark theme renders correctly (0 black px).

Three guards:
(a) light `_calendar_qss` must contain a QAbstractItemView `background` rule
    whose value is a theme_palette() token (parse the emitted qss string).
(b) offscreen render probe: light-theme calendar grab must have 0 opaque-black
    pixels (count via QImage).
(c) dark theme must stay 0 opaque-black pixels (no dark behavior change).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _palette_hexes(p):
    return {v for v in p.values() if isinstance(v, str) and v.startswith("#")}


def test_light_calendar_qss_has_background_rule():
    """浅色 _calendar_qss 的 QAbstractItemView 规则必须含 background 令牌。

    回归：date_theme.py:29-33 只设 selection-background-color/selection-color/
    color，缺 background → 全局 QSS `QFrame{background:transparent}` 让
    QStyleSheetStyle 把视图 Base 解析为 rgba(0,0,0,255)，日历体整片不透明黑。
    """
    from core.theme.tokens import theme_palette
    from modules.todo_notes.date_theme import _calendar_qss
    try:
        _force_dark(False)
        p = theme_palette()
        qss = _calendar_qss(p)
        m = re.search(r"QCalendarWidget QAbstractItemView\s*\{([^}]*)\}", qss)
        assert m, f"浅色日历 QSS 应含 QAbstractItemView 规则，实际: {qss}"
        rule = m.group(1)
        bm = re.search(r"background:\s*([^;]+);", rule)
        assert bm, f"QAbstractItemView 规则应设置 background，实际: {rule}"
        value = bm.group(1).strip()
        assert value in _palette_hexes(p), \
            f"background 值 {value} 必须是 theme_palette() 令牌，实际: {value}"
    finally:
        _restore_dark()


def _opaque_black_count(img):
    """统计 QImage 中完全不透明黑 (0,0,0,255) 像素数。"""
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255 and c.red() == 0 and c.green() == 0 and c.blue() == 0:
                n += 1
    return n


def _build_calendar():
    """真实 QDateEdit + 日历弹窗 + _apply_date_theme（与 _TodoEditDialog 同路径）。"""
    from modules.todo_notes.date_theme import _apply_date_theme
    de = QtWidgets.QDateEdit()
    de.setCalendarPopup(True)
    _apply_date_theme(de)
    cal = de.calendarWidget()
    cal.show()
    for _ in range(40):
        QtWidgets.QApplication.processEvents()
    return de, cal


def _calendar_black_count(dark):
    """强制主题 → 应用全局 QSS → 构建日历 → 抓图 → 统计不透明黑像素。"""
    from core.theme.styles import apply_global_stylesheet
    app = QtWidgets.QApplication.instance()
    saved = app.styleSheet()
    try:
        _force_dark(dark)
        apply_global_stylesheet(dark=dark)
        de, cal = _build_calendar()
        try:
            img = cal.grab().toImage()
            img.setDevicePixelRatio(1.0)
            return _opaque_black_count(img)
        finally:
            cal.hide()
            de.deleteLater()
            for _ in range(5):
                QtWidgets.QApplication.processEvents()
    finally:
        app.setStyleSheet(saved)
        _restore_dark()


def test_light_calendar_body_not_opaque_black(qapp):
    """浅色主题下日历体不得渲染不透明黑（回归：62,441 黑像素事故）。"""
    assert _calendar_black_count(False) == 0, \
        "浅色主题日历体渲染出不透明黑（QAbstractItemView 缺 background 规则）"


def test_dark_calendar_body_still_zero_black(qapp):
    """深色主题日历体保持 0 不透明黑（不得改动暗色行为）。"""
    assert _calendar_black_count(True) == 0, \
        "深色主题日历体不应出现不透明黑"