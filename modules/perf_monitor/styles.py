"""perf_monitor 主题与样式：perf_palette/_qcolor/_nice_ceil/_smooth_path 及四段 QSS 构建。"""
import math
import re
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
_, QtCore, QtGui, QtWidgets = import_qt()


def perf_palette():
    """perf 图表色板 = 全局色板 + perf 图表扩展（值全部来自 theme_palette）。"""
    p = dict(theme_palette())  # 拷贝，避免污染全局
    return p  # 扩展 key 已在 theme_palette 内（perf_* 前缀）


def _qcolor(css):
    """把 '#hex' 或 'rgba(r,g,b,a)' 等 CSS 颜色字符串解析为 QColor，失败时回退灰色。"""
    s = (css or "").strip()
    if s.startswith("#"):
        c = QtGui.QColor(s)
        return c if c.isValid() else QtGui.QColor(128, 128, 128)
    m = re.match(
        r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+)\s*)?\)", s)
    if m:
        c = QtGui.QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        a = m.group(4)
        if a is not None:
            alpha = float(a)
            c.setAlpha(int(alpha if alpha > 1 else alpha * 255))
        return c
    c = QtGui.QColor(s)
    return c if c.isValid() else QtGui.QColor(128, 128, 128)


def _nice_ceil(v):
    """把 y 轴上限取整到规整刻度（1 / 2 / 2.5 / 5 的 10 的幂次）。"""
    if v <= 0:
        return 10.0
    exp = math.floor(math.log10(v))
    base = 10.0 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * base:
            return m * base
    return 10.0 * base


def _smooth_path(points):
    """用三次贝塞尔把折线平滑成曲线（逐段以中点作控制点）。"""
    if not points:
        return QtGui.QPainterPath()
    path = QtGui.QPainterPath(points[0])
    if len(points) < 2:
        return path
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        c1 = QtCore.QPointF((p1.x() + p2.x()) / 2, p1.y())
        c2 = QtCore.QPointF((p1.x() + p2.x()) / 2, p2.y())
        path.cubicTo(c1, c2, p2)
    return path


def _group_box_style(tc):
    sz = sizing()
    return (
        f"QGroupBox {{ border: 1px solid {tc['perf_group_border']};"
        f" border-radius: {sz['radius_lg']}px;"
        f" background: {tc['perf_group_bg']}; margin-top: {sz['perf_group_margin_top']}px;"
        f" padding: {sz['perf_group_padding']}; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;"
        f" left: 12px; top: 2px; padding: {sz['perf_title_padding']};"
        f" color: {tc['text_primary']}; }}"
    )


def _ctrl_frame_style(tc):
    sz = sizing()
    return (
        f"QFrame#ctrl {{ border: 1px solid {tc['border']};"
        f" border-radius: {sz['radius_lg']}px;"
        f" background: {tc['bg_control']}; }}"
    )


def _table_style(tc):
    sz = sizing()
    return (
        "QTableWidget { border: none; background: transparent;"
        f" gridline-color: {tc['perf_grid_color']}; }}"
        f"QTableWidget::item {{ padding: {sz['perf_item_padding']}; }}"
        f"QTableWidget::item:selected {{ background: {tc['bg_selected']}; }}"
        "QTableWidget::item:hover { background: transparent; }"
        f"QTableWidget::item:selected:hover {{ background: {tc['bg_selected']}; }}"
    )


def _tabs_style(tc):
    """统一标签页样式：下划线式选中态，面板透明。

    与全局 QSS（qss_light/qss_dark 的 QTabBar 规则）令牌一致，避免漂移：
    颜色取 tab_* 令牌、尺寸取 tab_* sizing 令牌。额外保留
    `QTabWidget QWidget { background: transparent; }` 使 tab 内容透明。
    """
    sz = sizing()
    return (
        "QTabWidget::pane { background: transparent; border: none; }"
        "QTabWidget::tab-bar { alignment: left; }"
        f"QTabBar::tab {{ background: transparent; color: {tc['tab_text']};"
        f" padding: {sz['tab_padding']}; border: none; margin: {sz['tab_margin']}; }}"
        f"QTabBar::tab:hover {{ color: {tc['tab_text_hover']}; }}"
        f"QTabBar::tab:selected {{ color: {tc['tab_text_selected']};"
        f" background: {tc['tab_bg_selected']};"
        f" border-bottom: {sz['tab_indicator_height']}px solid {tc['tab_indicator']};"
        " font-weight: 600; }"
        "QTabWidget QWidget { background: transparent; }"
    )