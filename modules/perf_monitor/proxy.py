"""perf_monitor 排序代理：_SortFilterProxy。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
class _SortFilterProxy(QtCore.QSortFilterProxyModel):
    """按 UserRole float 排序数值列，字符串列按文字排。"""

    def lessThan(self, left, right):
        lv = left.data(QtCore.Qt.UserRole)
        rv = right.data(QtCore.Qt.UserRole)
        if lv is not None and rv is not None:
            try:
                return float(lv) < float(rv)
            except (TypeError, ValueError):
                pass
        return super().lessThan(left, right)
