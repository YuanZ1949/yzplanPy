"""todo_notes 表格 hover 反馈：整行描边而非整行填充。

回归保护：delegate.paint() 对 hover 行画的是「一圈描边」而不是
「整行柔色填充」。判定方式——hover 前后对比 viewport 快照：
行中心像素必须不变（无填充），行边缘像素必须变化（有描边）。
"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.todo_notes.delegate import _TodoItemDelegate


def _make_table(qapp):
    """构造带 delegate 的 QTableWidget（2 行 4 列，空文本 item）。"""
    table = QtWidgets.QTableWidget(2, 4)
    for r in range(2):
        for c in range(4):
            table.setItem(r, c, QtWidgets.QTableWidgetItem(""))
    for c in range(4):
        table.setColumnWidth(c, 100)
    table.setRowHeight(0, 40)
    table.setRowHeight(1, 40)
    # 加宽到 500：4 列 × 100px 全部落在 viewport 内（400 宽时横向滚动条
    # 出现，最后一列右缘被裁出视口，grab 采样到未绘制黑像素）
    table.resize(500, 120)
    delegate = _TodoItemDelegate(table)
    table.setItemDelegate(delegate)
    table._hover_row = -1
    table.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return table, delegate


def _snapshot(table):
    """viewport 快照 + DPR 感知采样器。

    grab() 返回的位图可能带 devicePixelRatio（高 DPI 下为 2），
    visualItemRect 给的是逻辑坐标，必须乘 DPR 才能取到正确像素。
    """
    img = table.viewport().grab().toImage()
    dpr = img.devicePixelRatio() or 1.0

    def sample(x, y):
        return img.pixelColor(int(x * dpr), int(y * dpr))

    return sample


def _refresh(table):
    table.viewport().update()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def test_hover_paints_border_not_fill(qapp):
    table, delegate = _make_table(qapp)
    rect0 = table.visualItemRect(table.item(0, 0))
    last_rect = table.visualItemRect(table.item(0, table.columnCount() - 1))
    # 行 0 中心：第 1 列中心（远离任何描边与复选框）
    center = rect0.center() + QtCore.QPoint(rect0.width(), 0)
    # 描边落点（drawRect 的 1px pen 画在几何边界上）：
    #   左缘 = rect.left()+1，右缘 = rect.right()，上缘 = rect.top()+1，下缘 = rect.bottom()
    mid_y = rect0.center().y()
    mid_x = center.x()
    edges = {
        "left": QtCore.QPoint(rect0.left() + 1, mid_y),
        "right": QtCore.QPoint(last_rect.right(), mid_y),
        "top": QtCore.QPoint(mid_x, rect0.top() + 1),
        "bottom": QtCore.QPoint(mid_x, rect0.bottom()),
    }

    # 基线：无 hover
    table._hover_row = -1
    _refresh(table)
    base = _snapshot(table)
    base_center = base(center.x(), center.y())
    base_edges = {k: base(p.x(), p.y()) for k, p in edges.items()}

    # hover 第 0 行
    table._hover_row = 0
    _refresh(table)
    hover = _snapshot(table)
    hover_center = hover(center.x(), center.y())
    hover_edges = {k: hover(p.x(), p.y()) for k, p in edges.items()}

    # 中心像素不变 → 无整行填充
    assert hover_center == base_center, \
        f"hover 不应填充行中心: base={base_center.name()} hover={hover_center.name()}"
    # 四缘像素变化 → 有描边
    for k in edges:
        assert hover_edges[k] != base_edges[k], \
            f"hover 应在行{k}缘画描边: base={base_edges[k].name()} hover={hover_edges[k].name()}"