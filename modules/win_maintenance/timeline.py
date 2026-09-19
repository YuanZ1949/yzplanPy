"""win_maintenance 错误时间线容器：时间范围选择栏 + 甘特图（图在 timeline_chart）。

本模块只保留容器逻辑（范围按钮、store 刷新、滚动区装配），
纯 QPainter 图表与绘制辅助函数在 timeline_chart.py（<250 行）。
"""
import datetime

from core.qt_bootstrap import import_qt
from core.theme.tokens import _s, sizing, theme_palette

from .timeline_chart import (
    _ChartWidget,
    _LEVEL_COLOR_KEY,  # noqa: F401  (测试经 timeline 模块引用)
    _elide_label,      # noqa: F401  (测试经 timeline 模块引用)
)

_, QtCore, QtGui, QtWidgets = import_qt()

# 时间范围选项（秒）
_RANGE_SECONDS = {"1h": 3600, "24h": 86400, "7d": 604800}
_RANGE_ORDER = ("1h", "24h", "7d")


class _ErrorTimeline(QtWidgets.QWidget):
    """甘特式错误时间线：时间范围选择栏 + 纯 QPainter 图表。"""

    def __init__(self, store, parent=None, config=None):
        super().__init__(parent)
        self._store = store
        self._current_range = "24h"
        self._groups = []
        self._config = config
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        from qfluentwidgets import BodyLabel
        bar.addWidget(BodyLabel("时间范围:"))
        self._range_buttons = {}
        for name in _RANGE_ORDER:
            btn = QtWidgets.QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(name == self._current_range)
            btn.clicked.connect(lambda _c=False, n=name: self._set_range(n))
            self._range_buttons[name] = btn
            bar.addWidget(btn)
        bar.addStretch(1)
        self._summary = BodyLabel("")
        bar.addWidget(self._summary)
        lay.addLayout(bar)

        self._scroll = QtWidgets.QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._chart = _ChartWidget(self._scroll, config=self._config)
        self._scroll.setWidget(self._chart)
        lay.addWidget(self._scroll, 1)

    @property
    def bar_rects(self):
        return self._chart.bar_rects

    def set_groups(self, groups):
        """直接设置组数据（测试用），绕过 store 刷新。"""
        self._groups = groups or []
        self._chart.set_groups(self._groups)

    def _set_range(self, name):
        self._current_range = name
        for n, btn in self._range_buttons.items():
            btn.setChecked(n == name)
        self._refresh()

    def _refresh(self):
        now = datetime.datetime.now()
        delta = datetime.timedelta(seconds=_RANGE_SECONDS[self._current_range])
        date_from = (now - delta).strftime("%Y-%m-%d %H:%M:%S")
        try:
            # 优先按 source 聚合（行数 = 来源数，行内 children 多色区分）；
            # 旧 store（无该方法）或测试替身回退到精确分组。
            try:
                rows = self._store.aggregate_errors_by_source(date_from=date_from) or []
            except (AttributeError, TypeError):
                rows = self._store.aggregate_errors(date_from=date_from) or []
        except TypeError:
            rows = self._store.aggregate_errors() or []
        self._groups = rows
        self._chart.set_groups(self._groups)
        total = sum(g.get("count", 0) for g in self._groups)
        self._summary.setText(
            f"共 {len(self._groups)} 组 · 覆盖事件 {total} 次 · {self._current_range}")