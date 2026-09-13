"""windows QPA 像素取证断言工具（L2）。

widget.grab() 在 windows QPA 下为该 widget 自身离屏渲染快照：透明区域
alpha=0，不混入父窗口/壁纸，因此可以"本控件无盒底/无边框/内容几何"
直接判定，无需与邻居对比、不锚定绝对色值，明暗主题通用。

约定：所有断言仅依赖 alpha 通道与几何，避免主题色差异导致的假阴性。
"""

from PySide6 import QtGui
from PySide6.QtCore import QPoint, QRect

# 背景盒 alpha 阈值：Fluent 白底弹片盒 alpha≈178；透明 QSS 残留也应 <40
BG_ALPHA_MAX = 40
# 边框线 alpha 阈值：border-bottom rgba(0,0,0,0.183)≈47
BORDER_ALPHA_MAX = 40


def grab(widget):
    """widget.grab() 快照（windows QPA 下真实样式渲染）。"""
    return widget.grab().toImage()


def _logical_to_physical(image, x, y):
    """逻辑坐标（widget 坐标系）→ 图像物理坐标（DPI 缩放）。"""
    dpr = image.devicePixelRatio()
    return QPoint(int(x * dpr), int(y * dpr))


def alpha_at(image, x, y):
    """逻辑坐标处像素 alpha（widget 区域外视为越界返回 255 以暴露 bug）。"""
    p = _logical_to_physical(image, x, y)
    if not (0 <= p.x() < image.width() and 0 <= p.y() < image.height()):
        return 255
    return image.pixelColor(p.x(), p.y()).alpha()


def max_row_alpha(image, y_logic, x_lo=0, x_hi=None):
    """逻辑横线上采样区间的最大 alpha（检测背景盒/边框线）。"""
    if x_hi is None:
        x_hi = image.width() // max(1, image.devicePixelRatio())
    return max(alpha_at(image, x, y_logic) for x in range(x_lo, x_hi))


def non_transparent_bbox(image, alpha_min=10):
    """扫描非透明像素（alpha≥alpha_min）的包围盒，返回逻辑坐标 QRect。

    空图返回 QRect()（isNull()）。用于"内容垂直居中"判定。
    """
    dpr = image.devicePixelRatio()
    w = image.width()
    h = image.height()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for py in range(0, h):
        for px in range(0, w):
            if image.pixelColor(px, py).alpha() >= alpha_min:
                if px < min_x:
                    min_x = px
                if px > max_x:
                    max_x = px
                if py < min_y:
                    min_y = py
                if py > max_y:
                    max_y = py
    if max_x < 0:
        return QRect()
    return QRect(min_x // dpr, min_y // dpr,
                 (max_x - min_x) // dpr + 1, (max_y - min_y) // dpr + 1)


def assert_no_box_background(image, widget_width, widget_height,
                             margin=2, alpha_max=BG_ALPHA_MAX):
    """目标控件无整块背景盒：四角与上下边缘中点采样 alpha 均极低。

    采样点刻意避开内容中带（文字/箭头垂直居中于此，中心点会误中文字
    抗锯齿像素）；白底弹片盒铺满包含四角，四角即可判定。
    """
    xs = [margin, widget_width - margin - 1]
    xs += [widget_width // 2]  # 上下边缘中点（内容带上下方）
    ys = [margin, widget_height - margin - 1]
    for x in xs:
        for y in ys:
            a = alpha_at(image, x, y)
            if a > alpha_max:
                raise AssertionError(
                    f"背景盒残留：像素({x},{y}) alpha={a} > {alpha_max}"
                    f"（透明 QSS 应为 0~极低；Fluent 白底盒≈178）")


def assert_no_bottom_border(image, widget_width, widget_height,
                            thickness=2, alpha_max=BORDER_ALPHA_MAX):
    """底部 thickness 逻辑像素行无深色边框线（防 border-bottom 被 28px 截断回归）。"""
    for y in range(widget_height - thickness, widget_height):
        a = max_row_alpha(image, y, 0, widget_width)
        if a > alpha_max:
            raise AssertionError(
                f"底部边框线残留：y={y} 行 max alpha={a} > {alpha_max}"
                f"（border-bottom 深色线≈183·0.183≈47）")


def assert_content_vcentered(image, widget_height, tolerance=2):
    """非透明内容包围盒垂直中线与控件中线偏差 ≤ tolerance 逻辑 px。"""
    bbox = non_transparent_bbox(image)
    if bbox.isNull():
        raise AssertionError("控件内没有任何可见内容像素")
    content_cy = bbox.y() + bbox.height() / 2
    widget_cy = widget_height / 2
    if abs(content_cy - widget_cy) > tolerance:
        raise AssertionError(
            f"内容未垂直居中：内容中线 {content_cy:.1f} vs 控件中线 {widget_cy}"
            f"（偏差 {abs(content_cy - widget_cy):.1f}px > {tolerance}px）")


def assert_text_not_overlapped_by_arrow(btn, label, gap_min=2):
    """几何断言：真实字体下文字右缘必须在自绘箭头区（width()-22）之前。

    Fluent DropDownButtonBase 在 paintEvent 自绘箭头于
    QRectF(self.width()-22, ... 10x10)；sizeHint 不含箭头宽。用真实
    fontMetrics 计算（windows QPA 下为 Segoe UI，离屏虚高 2-3 倍不可用）。
    """
    from PySide6.QtGui import QFontMetrics

    fm = QFontMetrics(btn.font())
    tw = fm.horizontalAdvance(label)
    w = btn.width()
    # text-align: left（迁移 QSS）→ 文字从 padding-left=8 开始
    text_right = 8 + tw
    arrow_left = w - 22
    gap = arrow_left - text_right
    if gap < gap_min:
        raise AssertionError(
            f"文字与箭头重叠：'{label}' 文字右缘 {text_right}px"
            f" 箭头起点 {arrow_left}px（gap={gap}px < {gap_min}px）")