"""Todo 9: 主题补齐标准控件边框 + 按钮文字/图标不重叠。"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _sheet(dark):
    if dark:
        from core.theme.qss_dark import _apply_dark_sheet

        _apply_dark_sheet(False)
    else:
        from core.theme.qss_light import _apply_light_sheet

        _apply_light_sheet(False)
    return QtWidgets.QApplication.instance().styleSheet()


def test_dark_sheet_has_standard_control_borders(_qapp):
    s = _sheet(True)
    assert "QPlainTextEdit, QTextEdit" in s, "深色主题应补齐多行输入框边框"
    assert "QCheckBox::indicator" in s, "深色主题应补齐复选框指示器边框"
    assert "QTableWidget" in s, "深色主题应补齐表格边框"
    assert "QHeaderView::section" in s, "深色主题应补齐表头（含复选框列）边框"
    assert "padding: 0 8px" in s, "深色主题 QToolButton 应有全局内边距"


def test_light_sheet_has_standard_control_borders(_qapp):
    s = _sheet(False)
    assert "QPlainTextEdit, QTextEdit" in s, "浅色主题应补齐多行输入框边框"
    assert "QCheckBox::indicator" in s, "浅色主题应补齐复选框指示器边框"
    assert "QTableWidget" in s, "浅色主题应补齐表格边框"
    assert "QHeaderView::section" in s, "浅色主题应补齐表头（含复选框列）边框"
    assert "padding: 0 8px" in s, "浅色主题 QToolButton 应有全局内边距"


def _render(btn, w, h, bg):
    """将按钮渲染到纯色背景 QImage（布局像素差分用）。"""
    pm = QtGui.QPixmap(w, h)
    pm.fill(bg)
    btn.render(pm)
    return pm.toImage()


def _diff_blobs(img_a, img_b, thresh=40):
    """两渲染之间差异像素的连通块列表 [(minx, miny, w, h), ...]（4 邻接）。"""
    w, h = min(img_a.width(), img_b.width()), min(img_a.height(), img_b.height())
    diff = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            ca, cb = img_a.pixelColor(x, y), img_b.pixelColor(x, y)
            d = (abs(ca.red() - cb.red()) + abs(ca.green() - cb.green())
                 + abs(ca.blue() - cb.blue()))
            diff[y][x] = d > thresh
    blobs, seen = [], [[False] * w for _ in range(h)]
    for sy in range(h):
        for sx in range(w):
            if not diff[sy][sx] or seen[sy][sx]:
                continue
            stack, seen[sy][sx] = [(sx, sy)], True
            minx, miny, maxx, maxy = sx, sy, sx, sy
            while stack:
                x, y = stack.pop()
                minx, miny, maxx, maxy = min(minx, x), min(miny, y), \
                    max(maxx, x), max(maxy, y)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and diff[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            blobs.append((minx, miny, maxx - minx + 1, maxy - miny + 1))
    return blobs


def test_title_bar_icon_text_no_overlap(_qapp):
    """定制标题栏 icon+文字按钮：图标与文字必须水平分离（>=2px）。

    背景：QStyleSheetStyle 对 QToolButton+ToolButtonTextBesideIcon 有布局
    缺陷——图标绘制在文字上（见 ui/module_pages.py 注释）。标题栏按钮因此
    改用 QPushButton 体系。测试用像素差分（真实图标 vs 同尺寸空白图标）分别
    定位图标/文字区域并断言互不相交；若回归到 ToolButton，断言必失败。
    """
    from qfluentwidgets import FluentIcon, PushButton, ToolButton

    bg = QtGui.QColor(30, 30, 46)
    app = _qapp
    saved_sheet = app.styleSheet()
    app.setStyleSheet("")  # 隔离本模块主题测试残留的 app 级 QSS，保证渲染确定性
    try:
        def blank_icon(size=16):
            pm = QtGui.QPixmap(size, size)
            pm.fill(bg)
            return QtGui.QIcon(pm)

        def build(kind, icon, text):
            btn = (ToolButton(FluentIcon.SETTING, None) if kind == "ToolButton"
                   else PushButton(text, None, FluentIcon.SETTING))
            if icon is not None:
                btn.setIcon(icon)
            btn.setText(text)
            return btn

        for kind in ("ToolButton", "PushButton"):
            probe = build(kind, None, "设置")
            probe.adjustSize()
            w = max(probe.sizeHint().width() + 6, 56)
            a = build(kind, FluentIcon.SETTING, "设置")
            b = build(kind, blank_icon(), "设置")
            c = build(kind, blank_icon(), "")
            for btn in (probe, a, b, c):
                btn.setFixedSize(w, 32)
            img_a, img_b, img_c = (_render(btn, w, 32, bg) for btn in (a, b, c))
            icon_blobs = [bb for bb in _diff_blobs(img_a, img_b) if bb[3] >= 12]
            text_blobs = [bb for bb in _diff_blobs(img_b, img_c) if bb[3] < 14]
            assert icon_blobs, f"{kind}: 图标未渲染"
            assert text_blobs, f"{kind}: 文字未渲染"
            icon_x = (min(bb[0] for bb in icon_blobs),
                      max(bb[0] + bb[2] - 1 for bb in icon_blobs))
            text_x = (min(bb[0] for bb in text_blobs),
                      max(bb[0] + bb[2] - 1 for bb in text_blobs))
            gap = text_x[0] - icon_x[1]
            if kind == "ToolButton":
                assert gap < 2, (
                    f"预期 ToolButton 存在重叠缺陷（QToolButton+TextBesideIcon），"
                    f"但实测 gap={gap} 无重叠——若 Qt 已修复可考虑换回；icon x={icon_x}, text x={text_x}")
            else:
                assert gap >= 2, (
                    f"PushButton 图标与文字重叠：icon x={icon_x}, text x={text_x}, "
                    f"gap={gap}（图标应严格在文字左侧）")
    finally:
        app.setStyleSheet(saved_sheet)