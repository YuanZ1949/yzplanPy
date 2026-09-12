"""win_maintenance 模块页：日志列表 + 过滤 + 导出（只读）。"""
import csv
import datetime

from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton

_, QtCore, QtGui, QtWidgets = import_qt()

from .store import read_event_log, get_log_stats, LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO

_PAGE_SIZE = 50
_MAX_READ = 2000
_MSG_PREVIEW = 100

_TIME_RANGES = (
    ("最近1小时", 3600),
    ("最近24小时", 86400),
    ("最近7天", 7 * 86400),
    ("最近30天", 30 * 86400),
)

_LEVELS = (
    ("错误", LEVEL_ERROR, "status_error"),
    ("警告", LEVEL_WARNING, "status_warning"),
    ("信息", LEVEL_INFO, "status_info"),
)

_COL_HEADERS = ("时间", "来源", "级别", "事件ID", "消息摘要")
_COL_WIDTHS = (150, 140, 60, 70, 0)  # 0 = 消息摘要列 stretch


class _LogPage(QtWidgets.QWidget):
    """日志列表页：过滤栏 + 统计栏 + 表格 + 分页 + CSV 导出。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._rows = []
        self._page = 1
        self._build_ui()
        self._refresh()

    # ── UI 构建 ──────────────────────────────────────────────
    def _build_ui(self):
        p = theme_palette()
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
        for name, code, _color in _LEVELS:
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(True)
            self._checks[code] = cb
            bar.addWidget(cb)

        self._edit_kw = QtWidgets.QLineEdit()
        self._edit_kw.setPlaceholderText("关键词...")
        self._edit_kw.setClearButtonEnabled(True)
        self._edit_kw.setMaximumWidth(160)
        bar.addWidget(self._edit_kw)

        self._combo_range = ComboBox()
        for label, secs in _TIME_RANGES:
            self._combo_range.addItem(label, userData=secs)
        self._combo_range.setMinimumWidth(110)
        bar.addWidget(self._combo_range)

        btn_refresh = PrimaryPushButton("刷新")
        btn_refresh.clicked.connect(self._refresh)
        bar.addWidget(btn_refresh)

        btn_export = PushButton("导出 CSV")
        btn_export.clicked.connect(self._export_csv)
        bar.addWidget(btn_export)
        bar.addStretch(1)
        lay.addLayout(bar)

        # 统计栏
        stats_bar = QtWidgets.QHBoxLayout()
        stats_bar.setSpacing(12)
        self._stats_labels = {}
        for name, _code, color in _LEVELS:
            lb = BodyLabel(f"{name} 0")
            lb.setStyleSheet(f"color: {p[color]};")
            stats_bar.addWidget(lb)
            self._stats_labels[name] = lb
        stats_bar.addStretch(1)
        lay.addLayout(stats_bar)

        # 表格
        self._table = QtWidgets.QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        self._table.horizontalHeader().setStretchLastSection(False)
        for col, w in enumerate(_COL_WIDTHS):
            if w:
                self._table.setColumnWidth(col, w)
            else:
                self._table.horizontalHeader().setSectionResizeMode(
                    col, QtWidgets.QHeaderView.Stretch)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellDoubleClicked.connect(self._show_detail)
        lay.addWidget(self._table, 1)

        # 分页栏
        page_bar = QtWidgets.QHBoxLayout()
        self._btn_prev = PushButton("上一页")
        self._btn_prev.clicked.connect(lambda: self._goto(self._page - 1))
        self._btn_next = PushButton("下一页")
        self._btn_next.clicked.connect(lambda: self._goto(self._page + 1))
        self._page_label = BodyLabel("第 1/1 页")
        page_bar.addStretch(1)
        page_bar.addWidget(self._btn_prev)
        page_bar.addWidget(self._page_label)
        page_bar.addWidget(self._btn_next)
        page_bar.addStretch(1)
        lay.addLayout(page_bar)

        # 过滤条件变化即刷新
        self._combo_type.currentIndexChanged.connect(self._refresh)
        self._combo_range.currentIndexChanged.connect(self._refresh)
        self._edit_kw.returnPressed.connect(self._refresh)
        for cb in self._checks.values():
            cb.toggled.connect(self._refresh)

    # ── 数据刷新 ─────────────────────────────────────────────
    def _current_levels(self):
        checked = [code for code, cb in self._checks.items() if cb.isChecked()]
        return checked or None

    def _refresh(self):
        log_type = self._combo_type.currentData() or "System"
        secs = self._combo_range.currentData() or 86400
        date_from = datetime.datetime.now() - datetime.timedelta(seconds=secs)
        kw = self._edit_kw.text().strip() or None
        self._rows = read_event_log(
            log_type=log_type, level=self._current_levels(),
            keyword=kw, date_from=date_from, limit=_MAX_READ)
        self._page = 1
        self._update_stats(log_type)
        self._populate()

    def _update_stats(self, log_type):
        stats = get_log_stats(log_type)
        for name, _code, _color in _LEVELS:
            self._stats_labels[name].setText(f"{name} {stats.get(name, 0)}")

    # ── 表格填充 ─────────────────────────────────────────────
    def _page_count(self):
        return max(1, (len(self._rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)

    def _populate(self):
        p = theme_palette()
        total = self._page_count()
        self._page = min(max(1, self._page), total)
        start = (self._page - 1) * _PAGE_SIZE
        slice_rows = self._rows[start:start + _PAGE_SIZE]
        self._table.setRowCount(len(slice_rows))
        for r, row in enumerate(slice_rows):
            msg = row["message"] or ""
            preview = msg if len(msg) <= _MSG_PREVIEW else msg[:_MSG_PREVIEW] + "…"
            values = (row["time"], row["source"], row["level"],
                      str(row["event_id"]), preview)
            for c, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(msg)
                if row["level"] == "错误":
                    item.setForeground(QtGui.QColor(p["status_error"]))
                elif row["level"] == "警告":
                    item.setForeground(QtGui.QColor(p["status_warning"]))
                self._table.setItem(r, c, item)
        self._page_label.setText(f"第 {self._page}/{total} 页")
        self._btn_prev.setEnabled(self._page > 1)
        self._btn_next.setEnabled(self._page < total)

    def _goto(self, page):
        self._page = page
        self._populate()

    # ── 交互 ─────────────────────────────────────────────────
    def _show_detail(self, row, _col):
        if not (0 <= row < self._table.rowCount()):
            return
        item = self._table.item(row, 4)
        msg = item.toolTip() if item else ""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("事件详情")
        dlg.resize(560, 320)
        dlay = QtWidgets.QVBoxLayout(dlg)
        dlay.setContentsMargins(12, 12, 12, 12)
        info = BodyLabel(
            f"{self._table.item(row, 0).text()}  |  "
            f"{self._table.item(row, 1).text()}  |  "
            f"{self._table.item(row, 2).text()}  |  "
            f"事件ID {self._table.item(row, 3).text()}")
        dlay.addWidget(info)
        text = QtWidgets.QPlainTextEdit()
        text.setPlainText(msg)
        text.setReadOnly(True)
        dlay.addWidget(text, 1)
        btn_close = PushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        dlay.addWidget(btn_close, 0, QtCore.Qt.AlignRight)
        dlg.exec()

    def _export_csv(self):
        if not self._rows:
            return
        default_name = f"win_maintenance_{datetime.date.today():%Y%m%d}.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出 CSV", default_name, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["时间", "来源", "级别", "事件ID", "消息"])
                for row in self._rows:
                    writer.writerow([row["time"], row["source"], row["level"],
                                     row["event_id"], row["message"]])
        except OSError:
            pass


def _make_page_widget(owner, parent):
    return _LogPage(owner, parent)