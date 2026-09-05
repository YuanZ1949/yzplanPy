"""perf_monitor 主题与样式：_theme_colors/_qcolor/_nice_ceil/_smooth_path 及四段 QSS 构建。"""
import math
import re
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
def _theme_colors():
    from core.theme import resolve_dark
    dark = resolve_dark("auto")
    if dark:
        return {
            "dark": True,
            "accent": "#3aa6ff",
            "accent_pid": "#5b8cff",
            "accent_cpu": "#25c9a0",
            "accent_mem": "#a06bff",
            "accent_thr": "#ffab40",
            "accent_hdl": "#ff6b8a",
            "accent_uptime": "#4fd97a",
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "card_bg": "rgba(255,255,255,0.06)",
            "card_border": "rgba(255,255,255,0.10)",
            "ctrl_bg": "rgba(255,255,255,0.05)",
            "ctrl_border": "rgba(255,255,255,0.10)",
            "grid_color": "rgba(255,255,255,0.06)",
            "sel_bg": "rgba(0,120,215,0.25)",
            "text_primary": "#e6e6e6",
            "text_secondary": "#999999",
            "bar_colors": [
                (0, 180, 80),
                (60, 170, 50),
                (180, 160, 0),
                (220, 120, 0),
                (220, 60, 40),
            ],
        }
    return {
        "dark": False,
        "accent": "#1178e0",
        "accent_pid": "#4a77f5",
        "accent_cpu": "#12a582",
        "accent_mem": "#7c3aed",
        "accent_thr": "#e08a1e",
        "accent_hdl": "#e4506f",
        "accent_uptime": "#2f9e5a",
        "group_border": "rgba(0,0,0,0.10)",
        "group_bg": "rgba(0,0,0,0.02)",
        "card_bg": "rgba(0,0,0,0.03)",
        "card_border": "rgba(0,0,0,0.08)",
        "ctrl_bg": "rgba(0,0,0,0.03)",
        "ctrl_border": "rgba(0,0,0,0.08)",
        "grid_color": "rgba(0,0,0,0.06)",
        "sel_bg": "rgba(0,120,215,0.18)",
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "bar_colors": [
            (34, 160, 70),
            (70, 150, 40),
            (200, 160, 0),
            (210, 110, 0),
            (210, 50, 30),
        ],
    }


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
    return (
        f"QGroupBox {{ border: 1px solid {tc['group_border']}; border-radius: 8px;"
        f" background: {tc['group_bg']}; margin-top: 14px; padding: 8px 6px 6px 6px; }}"
        f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;"
        f" left: 12px; top: 2px; padding: 0 6px; color: {tc['text_primary']}; }}"
    )


def _ctrl_frame_style(tc):
    return (
        f"QFrame#ctrl {{ border: 1px solid {tc['ctrl_border']}; border-radius: 8px;"
        f" background: {tc['ctrl_bg']}; }}"
    )


def _table_style(tc):
    return (
        "QTableWidget { border: none; background: transparent;"
        f" gridline-color: {tc['grid_color']}; }}"
        "QTableWidget::item { padding: 2px 4px; }"
        f"QTableWidget::item:selected {{ background: {tc['sel_bg']}; }}"
        "QTableWidget::item:hover { background: transparent; }"
        f"QTableWidget::item:selected:hover {{ background: {tc['sel_bg']}; }}"
    )


def _tabs_style(tc):
    """统一标签页样式：下划线式选中态，面板透明。"""
    sec = tc["text_secondary"]
    pri = tc["text_primary"]
    accent = tc["accent"]
    return (
        "QTabWidget::pane { background: transparent; border: none; }"
        "QTabWidget::tab-bar { alignment: left; }"
        f"QTabBar::tab {{ background: transparent; color: {sec}; padding: 8px 16px;"
        " border: none; border-bottom: 2px solid transparent; }}"
        f"QTabBar::tab:hover {{ color: {pri}; }}"
        f"QTabBar::tab:selected {{ color: {pri}; font-weight: 600;"
        f" border-bottom: 2px solid {accent}; }}"
        "QTabWidget QWidget { background: transparent; }"
    )
