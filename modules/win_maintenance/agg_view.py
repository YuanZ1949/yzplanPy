"""win_maintenance 聚合时间线视图：按 (来源, 事件ID) 分组罗列同样报错及持续时间。"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton

_, QtCore, QtGui, QtWidgets = import_qt()

from .page import _LogPage
from . import store as _store
from .store import LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO
from ui.adaptive_table import make_adaptive_table

_COL_HEADERS = ("来源", "事件ID", "次数", "首次出现", "最近出现", "持续时长", "事件消息摘要")
_MSG_PREVIEW = 100


def _fmt_duration(sec) -> str:
    """秒数转中文时长；sec<=0 一律 '0秒'。"""
    if sec <= 0:
        return "0秒"
    if sec >= 86400:
        return f"{sec // 86400}天{sec % 86400 // 3600}小时"
    if sec >= 3600:
        return f"{sec // 3600}小时{sec % 3600 // 60}分"
    if sec >= 60:
        return f"{sec // 60}分{sec % 60}秒"
    return f"{sec}秒"


class _AggregationView(QtWidgets.QWidget):
    """聚合时间线：过滤栏 + 分组表 + 计数标签。"""

    def __init__(self, store, owner=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._owner = owner
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # 过滤栏
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self._combo_type = ComboBox()
        for t in ("System", "Application", "Security"):
            self._combo_type.addItem(t, userData=t)
        self._combo_type.setMinimumWidth(110)
        bar.addWidget(self._combo_type)

        self._checks = {}
        for name, code in (("错误", LEVEL_ERROR), ("警告", LEVEL_WARNING),
                           ("信息", LEVEL_INFO)):
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(True)
            self._checks[code] = cb
            bar.addWidget(cb)

        btn_refresh = PrimaryPushButton("刷新")
        btn_refresh.clicked.connect(self._refresh)
        bar.addWidget(btn_refresh)
        bar.addStretch(1)
        lay.addLayout(bar)

        # 分组表
        self._table = QtWidgets.QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        make_adaptive_table(self._table, width_caps={6: 0.35},
                            min_widths={1: 80, 2: 70, 3: 100, 4: 100, 5: 100})
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellDoubleClicked.connect(self._show_detail)
        lay.addWidget(self._table, 1)

        # 计数标签
        self._summary = BodyLabel("共 0 组 · 覆盖事件 0 次")
        lay.addWidget(self._summary)

        # 过滤条件变化即刷新
        self._combo_type.currentIndexChanged.connect(self._refresh)
        for cb in self._checks.values():
            cb.toggled.connect(self._refresh)

    def _current_levels(self):
        checked = [code for code, cb in self._checks.items() if cb.isChecked()]
        return checked or None

    def _refresh(self):
        p = theme_palette()
        rows = self._store.aggregate_errors(
            log_type=self._combo_type.currentData() or "System",
            level=self._current_levels())
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            msg = row["message"] or ""
            preview = msg if len(msg) <= _MSG_PREVIEW else msg[:_MSG_PREVIEW] + "…"
            values = (row["source"], str(row["event_id"]), str(row["count"]),
                      row["first_time"], row["last_time"],
                      _fmt_duration(row["duration_s"]), preview)
            for c, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(msg)
                if c == 2 and row["count"] > 10:
                    item.setForeground(QtGui.QColor(p["status_error"]))
                self._table.setItem(r, c, item)
        self._summary.setText(
            f"共 {len(rows)} 组 · 覆盖事件 {sum(r['count'] for r in rows)} 次")

    def _show_detail(self, row, _col):
        if not (0 <= row < self._table.rowCount()):
            return
        item = self._table.item(row, 6)
        msg = item.toolTip() if item else ""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("事件详情")
        dlg.resize(560, 320)
        dlay = QtWidgets.QVBoxLayout(dlg)
        dlay.setContentsMargins(12, 12, 12, 12)
        info = BodyLabel(
            f"{self._table.item(row, 0).text()} | 事件ID "
            f"{self._table.item(row, 1).text()} | 首次 "
            f"{self._table.item(row, 3).text()} ~ 最近 "
            f"{self._table.item(row, 4).text()}")
        dlay.addWidget(info)
        text = QtWidgets.QPlainTextEdit()
        text.setPlainText(msg)
        text.setReadOnly(True)
        dlay.addWidget(text, 1)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        dlay.addWidget(btn_close, 0, QtCore.Qt.AlignRight)
        dlg.exec()


class _MaintenancePage(QtWidgets.QWidget):
    """维护模块页：日志列表 tab + 聚合时间线 tab。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        tab = QtWidgets.QTabWidget()
        tab.addTab(_LogPage(owner, tab), "日志列表")
        tab.addTab(_AggregationView(_store, owner, tab), "聚合时间线")
        lay.addWidget(tab)