"""todo_notes 全选表头：_SelectAllHeader。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .constants import COL_CHECK
# ── 独立页面 ──────────────────────────────────────────────────────────

class _SelectAllHeader(QtWidgets.QHeaderView):
    """复选框列(首列)标题栏：绘制一个全选复选框，点击切换全部行勾选。"""

    _toggled = QtCore.Signal(bool)

    def __init__(self, table):
        super().__init__(QtCore.Qt.Horizontal, table)
        self.table = table
        self._checked = False
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def set_all_checked(self, checked):
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self.viewport().update()

    def paintSection(self, painter, rect, logical):
        painter.save()
        try:
            super().paintSection(painter, rect, logical)
        finally:
            painter.restore()
        if logical != COL_CHECK:
            return
        text = "取消" if self._checked else "全选"
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text)
        bw = tw + 16
        bh = fm.height() + 6
        bx = rect.center().x() - bw // 2
        by = rect.center().y() - bh // 2
        # 圆角矩形按钮边框
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = painter.pen()
        painter.setPen(QtGui.QPen(QtGui.QColor(128, 128, 128, 180), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(QtCore.QRect(bx, by, bw, bh), 4, 4)
        painter.setPen(pen)
        # 居中文字
        painter.drawText(QtCore.QRect(bx, by, bw, bh),
                         int(QtCore.Qt.AlignCenter), text)

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self.logicalIndexAt(pos) == COL_CHECK:
            self._toggled.emit(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)
