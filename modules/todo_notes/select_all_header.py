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
        st = QtWidgets.QStyle.State_Enabled
        st |= QtWidgets.QStyle.State_On if self._checked else QtWidgets.QStyle.State_Off
        opt = QtWidgets.QStyleOptionButton()
        opt.rect = QtCore.QRect(rect.center().x() - 8, rect.center().y() - 8, 16, 16)
        opt.state = st
        opt.text = ""
        self.style().drawPrimitive(QtWidgets.QStyle.PE_IndicatorCheckBox, opt, painter, self)

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self.logicalIndexAt(pos) == COL_CHECK:
            self._toggled.emit(not self._checked)
            event.accept()
            return
        super().mousePressEvent(event)
