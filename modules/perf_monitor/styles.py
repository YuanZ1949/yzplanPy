"""perf_monitor 主题与样式：_theme_colors/_qcolor/_nice_ceil/_smooth_path 及四段 QSS 构建。"""
import math
import re
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
def _theme_colors():
    """perf_monitor 调色板：全局 theme_palette 别名 + perf 专属扩展。

    阶段 2 试点：模块不再自创基准色；accent/text 等视觉色与全局令牌单一
    来源。perf 旧 key 名（card_bg/card_border/ctrl_bg/ctrl_border/sel_bg）
    映射到全局令牌值——key 收敛且视觉零变化（Task 1 已把全局 border 等
    对齐到 perf 基准值）；仅图表系列色（accent_pid/cpu/mem/thr/hdl/uptime、
    group_border/group_bg、grid_color、bar_colors）作为 perf 专属扩展保留。
    """
    from core.theme.tokens import theme_palette
    p = dict(theme_palette())  # 拷贝，避免污染全局
    dark = p["dark"]
    p.update({
        # perf 旧 key → 全局令牌值（key 收敛；test_theme_colors_returns_dict
        # 依赖这 5 个 key 存在，且此映射保证 perf 视觉与迁移前一致）
        "card_bg": p["bg_card"],
        "card_border": p["border"],
        "ctrl_bg": p["bg_control"],
        "ctrl_border": p["border"],
        "sel_bg": p["bg_selected"],
    })
    if dark:
        p.update({
            "accent_pid": "#5b8cff",
            "accent_cpu": "#25c9a0",
            "accent_mem": "#a06bff",
            "accent_thr": "#ffab40",
            "accent_hdl": "#ff6b8a",
            "accent_uptime": "#4fd97a",
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "grid_color": "rgba(255,255,255,0.06)",
            "bar_colors": [
                (0, 180, 80), (60, 170, 50), (180, 160, 0),
                (220, 120, 0), (220, 60, 40),
            ],
        })
    else:
        p.update({
            "accent_pid": "#4a77f5",
            "accent_cpu": "#12a582",
            "accent_mem": "#7c3aed",
            "accent_thr": "#e08a1e",
            "accent_hdl": "#e4506f",
            "accent_uptime": "#2f9e5a",
            "group_border": "rgba(0,0,0,0.10)",
            "group_bg": "rgba(0,0,0,0.02)",
            "grid_color": "rgba(0,0,0,0.06)",
            "bar_colors": [
                (34, 160, 70), (70, 150, 40), (200, 160, 0),
                (210, 110, 0), (210, 50, 30),
            ],
        })
    return p


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
