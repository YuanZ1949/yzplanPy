"""webview_control - full page widget."""
import os
import time
from datetime import datetime
from core.theme.tokens import sizing, theme_palette
from .hosts import kill_host_webview, scan_hosts
from .constants import HOST_STATUS_LABELS, host_status_colors
from .config import load_hidden_hosts, save_hidden_hosts
from .hidden_dialog import _visible_hosts, show_hidden_dialog

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

def _log_action_buttons(exe, on_action):
    """组装 放行/拦截/删除 三个操作按钮，返回承载 QWidget。

    on_action: callable(exe_str, action_str)，action ∈ {"allow","block","forget"}。
    """
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()
    from ui.widgets import make_button

    cell = QtWidgets.QWidget()
    hl = QtWidgets.QHBoxLayout(cell)
    hl.setContentsMargins(6, 2, 6, 2)
    hl.setSpacing(4)
    btn_allow = make_button("放行", size="md", parent=cell)
    btn_block = make_button("拦截", size="md", parent=cell)
    btn_forget = make_button("删除", size="md", parent=cell)
    for b in (btn_allow, btn_block, btn_forget):
        # 最小宽度保证窗口缩小时按钮文字（放行/拦截/删除）完整显示；
        # 高度由 make_button 固定为 btn_height_md，行高 webview_row_height 容纳之
        b.setMinimumWidth(56)
    btn_allow.clicked.connect(lambda _=False, e=exe: on_action(e, "allow"))
    btn_block.clicked.connect(lambda _=False, e=exe: on_action(e, "block"))
    btn_forget.clicked.connect(lambda _=False, e=exe: on_action(e, "forget"))
    hl.addWidget(btn_allow)
    hl.addWidget(btn_block)
    hl.addWidget(btn_forget)
    hl.addStretch(1)
    # 行高由 cell sizeHint 驱动，但 cell 实际高度 = 行高 - 1(gridline) - 2*item padding，
    # 恒比 sizeHint 矮 2*item padding（QSS QTableWidget::item padding 上下各 pad_v）。
    # 抬高 sizeHint 使行高容纳按钮 + 边距，按钮不再溢出 cell 底部。
    pad_v = int(sizing()["qss_table_item_padding"].split()[0][:-2])
    _orig_size_hint = cell.sizeHint
    cell.sizeHint = lambda: QtCore.QSize(
        _orig_size_hint().width(), _orig_size_hint().height() + 2 * pad_v)
    return cell

def _pending_entries(entries, view):
    """按视图过滤拦截记录：pending=仅待处置 / done=仅已处置 / all=全部。"""
    if view == "pending":
        return [e for e in entries if e.get("status") == "pending"]
    if view == "done":
        return [e for e in entries if e.get("status") != "pending"]
    return list(entries)


def _time_sort_key(value):
    """将时间字符串解析为时间戳用于排序；无法解析时返回 0.0。"""
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0


def _blocked_entries(entries, blocked_view):
    """按封禁状态过滤条目列表：blocked=仅已封禁 / unblocked=仅未封禁 / all=全部。"""
    if blocked_view == "blocked":
        return [e for e in entries if e.get("blocked")]
    if blocked_view == "unblocked":
        return [e for e in entries if not e.get("blocked")]
    return list(entries)


def _search_entries(entries, keyword):
    """按关键词过滤（程序名 + 地址，大小写不敏感）；空关键词返回全部。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return list(entries)
    return [e for e in entries
            if kw in e.get("name", "").lower() or kw in e.get("exe", "").lower()]


_SORTABLE_COLUMNS = {0: "name", 1: "exe", 2: "link_status", 3: "blocked",
                     4: "first_seen", 5: "last_seen", 6: "status", 7: "action"}

_STATUS_RANK = {"pending": 0, "allowed": 1, "blocked": 2}


def _link_status_rank(row):
    """链接状态排序键：已拦截(0) < 连接中(1) < 运行中·无连接(2) < 未运行(3)。"""
    if row.get("blocked"):
        return 0
    if not row.get("running"):
        return 3
    return 1 if row.get("connections", 0) > 0 else 2


def _sort_entries(rows, sort_key, order="asc"):
    """按 sort_key 排序条目列表；时间字段按真实时间排序。"""
    if sort_key not in ("name", "exe", "link_status", "blocked",
                        "first_seen", "last_seen", "status", "action"):
        return list(rows)
    if sort_key in ("first_seen", "last_seen"):
        key_fn = lambda r: _time_sort_key(r.get(sort_key))
    elif sort_key == "status":
        key_fn = lambda r: _STATUS_RANK.get(r.get(sort_key), 99)
    elif sort_key == "link_status":
        key_fn = lambda r: _link_status_rank(r)
    elif sort_key == "blocked":
        key_fn = lambda r: 1 if r.get("blocked") else 0
    elif sort_key == "action":
        key_fn = lambda r: 0  # 操作列无排序键 → 稳定保持原顺序
    else:
        key_fn = lambda r: r.get(sort_key, "").lower()
    return sorted(rows, key=key_fn, reverse=(order == "desc"))


def _column_display_value(row, col) -> str:
    """返回第 col 列在表格中显示的文字，用于按列筛选匹配。"""
    if col == 0:
        return row.get("name", "")
    if col == 1:
        return row.get("exe", "")
    if col == 2:
        if row.get("blocked"):
            return "已拦截"
        if not row.get("running"):
            return "未运行"
        if row.get("connections", 0) > 0:
            return f"连接中 ({row['connections']} 连接)"
        return "运行中·无连接"
    if col == 3:
        return "已封禁" if row.get("blocked") else "未封禁"
    if col == 4:
        return row.get("first_seen", "")
    if col == 5:
        return row.get("last_seen", "")
    if col == 6:
        status = row.get("status") or ""
        return HOST_STATUS_LABELS.get(status, status)
    if col == 7:
        return "放行 拦截 删除"
    return ""


def _filter_entries_by_column(rows, filters):
    """按列筛选：filters = {列号: 关键词}，大小写不敏感子串匹配，多列取交集。

    空/空白关键词不参与筛选；无有效筛选时返回 rows 的副本。
    """
    active = {col: kw.strip().lower() for col, kw in filters.items()
              if kw and kw.strip()}
    if not active:
        return list(rows)
    return [r for r in rows
            if all(kw in _column_display_value(r, col).lower()
                   for col, kw in active.items())]


class _ColumnFilter(QtCore.QObject):
    """按列筛选条：每列一个输入框，输入即触发 on_changed 回调。

    与 ui/adaptive_table._AdaptiveFilter 同模式：QObject 子类 + 工厂创建控件，
    调用方持有引用防止 Python 包装被 GC 导致信号失效。
    """

    def __init__(self, headers, on_changed, parent=None):
        super().__init__(parent)
        from ui.widgets import make_line_edit
        self._edits = {}
        self._on_changed = on_changed
        for col, header in enumerate(headers):
            edit = make_line_edit(header, parent=parent)
            edit.setMaximumWidth(110)
            edit.setToolTip(f"按「{header}」筛选")
            edit.textChanged.connect(self._changed)
            self._edits[col] = edit

    def _changed(self, *_):
        self._on_changed()

    def filters(self):
        return {col: e.text() for col, e in self._edits.items()}


def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, ComboBox, PushButton, StrongBodyLabel
    from ui.widgets import make_button, make_combo, make_line_edit

    _p = theme_palette()
    _sz = sizing()

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    desc = BodyLabel(
        "这里列出使用 WebView2 的第三方程序。封禁后会自动终止该程序的 WebView2 子进程，"
        "并在其后台持续拦截（程序重新打开 WebView2 也会被立即终止）。", w)
    desc.setWordWrap(True)
    desc.setStyleSheet(f"color: {_p['text_secondary']};")
    lay.addWidget(desc)

    toolbar = QtWidgets.QHBoxLayout()
    btn_refresh = PushButton("刷新")
    lb_count = BodyLabel("")
    lb_count.setStyleSheet(f"color: {_p['text_secondary']};")
    # 窄窗口（模块窗口最小 760px）下按钮/计数标签文字不被截断
    btn_refresh.setMinimumWidth(64)
    btn_refresh.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    lb_count.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    toolbar.addWidget(btn_refresh)
    toolbar.addWidget(lb_count)
    toolbar.addStretch(1)
    btn_hidden = make_button("隐藏项", kind="default", size="md", parent=w)
    toolbar.addWidget(btn_hidden)
    lay.addLayout(toolbar)

    # ── 过滤栏（处置状态 + 封禁状态 + 搜索） ──────────────────────
    filter_row = QtWidgets.QHBoxLayout()
    filter_row.setSpacing(8)
    filter_label = StrongBodyLabel("处置状态", w)
    filter_row.addWidget(filter_label)
    _log_view_combo = ComboBox()
    for label, value in (("待处置", "pending"), ("已处置", "done"), ("全部", "all")):
        _log_view_combo.addItem(label, userData=value)
    _log_view_combo.setCurrentIndex(2)   # 默认全部
    filter_row.addWidget(_log_view_combo)
    blocked_label = StrongBodyLabel("封禁状态", w)
    filter_row.addWidget(blocked_label)
    _blocked_combo = make_combo(parent=w)
    for label, value in (("已封禁", "blocked"), ("未封禁", "unblocked"), ("全部", "all")):
        _blocked_combo.addItem(label, userData=value)
    _blocked_combo.setCurrentIndex(2)   # 默认全部（保持既有行为）
    filter_row.addWidget(_blocked_combo)
    filter_row.addStretch(1)
    _search_input = make_line_edit("搜索程序名或地址...", parent=w)
    _search_input.setMaximumWidth(220)
    filter_row.addWidget(_search_input)
    lay.addLayout(filter_row)

    # ── 按列筛选条（每列一个输入框，与自适应表同模式） ──────────────
    _column_filter = _ColumnFilter(
        ["程序名", "程序地址", "链接状态", "封禁开关",
         "首次出现", "最近出现", "处置状态", "操作"],
        lambda: _populate(), parent=w)
    # 持有引用防 GC：PySide6 中父对象不保证 Python 包装存活，丢弃会导致信号失效
    w._column_filter = _column_filter
    filter_bar = QtWidgets.QHBoxLayout()
    filter_bar.setSpacing(6)
    for col in range(8):
        filter_bar.addWidget(_column_filter._edits[col])
    filter_bar.addStretch(1)
    lay.addLayout(filter_bar)

    # ── 合并表：一行 = 一个程序（实时扫描 + 拦截记录） ───────────────
    table = QtWidgets.QTableWidget()
    table.setColumnCount(8)
    table.setHorizontalHeaderLabels(
        ["程序名", "程序地址", "链接状态", "封禁开关",
         "首次出现", "最近出现", "处置状态", "操作"])
    from ui.adaptive_table import make_adaptive_table
    _stretch = make_adaptive_table(table, width_caps={1: 0.35},
                                   min_widths={3: 90, 4: 110, 5: 110, 6: 70, 7: 200})
    # 持有过滤器引用：PySide6 中父对象不保证 Python 包装存活，丢弃返回值
    # 会导致 eventFilter 失效（列宽不再随窗口自适应）
    w._stretch = _stretch
    table.verticalHeader().setDefaultSectionSize(_sz["webview_row_height"])
    table.setWordWrap(True)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(
        f"QTableWidget {{ border: none; background: transparent; gridline-color: {_p['table_gridline']}; }}"
        f"QTableWidget::item {{ selection-background-color: {_p['table_sel_strong_bg']}; }}")
    lay.addWidget(table, 1)

    status_bar = BodyLabel("")
    status_bar.setStyleSheet(f"color: {_p['text_secondary']};")
    lay.addWidget(status_bar)

    # 已生效/待生效的拦截开关（含重启后仍封禁的宿主导入）
    def _ordered_hosts():
        blocked = set(owner.blocked)
        running = [h for h in scan_hosts(blocked)]
        seen = {h["exe"] for h in running}
        # 补齐已封禁但当前未运行的宿主，方便放行
        for exe in sorted(blocked):
            if exe not in seen:
                running.append({
                    "exe": exe, "name": os.path.basename(exe).replace(".exe", "") or exe,
                    "running": False, "procs": [], "webview_count": 0,
                    "connections": 0, "blocked": True, "user_data_dirs": [],
                })
        running.sort(key=lambda h: (not h["blocked"], h["name"].lower()))
        return running

    _cached_hosts = []
    _sort_col = None
    _sort_order = "asc"

    def _populate():
        """合并实时扫描与拦截记录为单表：一行 = 一个程序。

        外连接键 = exe 路径（小写）。仅在扫描中出现的程序（无 host_log 记录）
        首次/最近出现取当前时间；仅存在于拦截记录的历史程序也保留为行。
        """
        hidden = set(load_hidden_hosts(owner.context.config))
        visible = _visible_hosts(_cached_hosts, hidden)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        log_by_exe = {e["exe"]: e for e in owner.host_log}
        rows = []
        seen = set()
        for h in visible:
            exe = h["exe"]
            seen.add(exe)
            ent = log_by_exe.get(exe)
            if ent:
                first_seen = ent.get("first_seen", now)
                last_seen = ent.get("last_seen", now)
                status = ent.get("status", "pending")
            else:
                first_seen = now
                last_seen = now
                status = "blocked" if h["blocked"] else "pending"
            rows.append({**h, "first_seen": first_seen, "last_seen": last_seen, "status": status})
        # 仅存在于拦截记录的历史程序（当前未运行）也保留为行
        for exe, ent in log_by_exe.items():
            if exe in seen or exe in hidden:
                continue
            rows.append({
                "exe": exe,
                "name": ent.get("name") or os.path.basename(exe).replace(".exe", "") or exe,
                "running": False, "procs": [], "webview_count": 0,
                "connections": 0, "blocked": ent.get("status") == "blocked",
                "user_data_dirs": [],
                "first_seen": ent.get("first_seen", now),
                "last_seen": ent.get("last_seen", now),
                "status": ent.get("status", "pending"),
            })
        view = _log_view_combo.currentData() or "pending"
        rows = _pending_entries(rows, view)
        rows = _blocked_entries(rows, _blocked_combo.currentData() or "all")
        rows = _search_entries(rows, _search_input.text())
        rows = _filter_entries_by_column(rows, _column_filter.filters())
        if _sort_col is not None:
            rows = _sort_entries(rows, _sort_col, _sort_order)
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            # 程序名
            name_item = QtWidgets.QTableWidgetItem(r["name"])
            table.setItem(i, 0, name_item)
            # 程序地址
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(r["exe"]))
            # 链接状态
            if r["blocked"]:
                link_item = QtWidgets.QTableWidgetItem("已拦截")
                link_item.setForeground(QtGui.QColor(_p["webview_blocked"]))
            elif not r["running"]:
                link_item = QtWidgets.QTableWidgetItem("未运行")
                link_item.setForeground(QtGui.QColor(_p["text_secondary"]))
            elif r["connections"] > 0:
                link_item = QtWidgets.QTableWidgetItem(f"连接中 ({r['connections']} 连接)")
                link_item.setForeground(QtGui.QColor(_p["webview_allowed"]))
            else:
                link_item = QtWidgets.QTableWidgetItem("运行中·无连接")
                link_item.setForeground(QtGui.QColor(_p["text_secondary"]))
            table.setItem(i, 2, link_item)
            # 封禁开关
            sw = QtWidgets.QWidget()
            sl = QtWidgets.QHBoxLayout(sw)
            sl.setContentsMargins(6, 2, 6, 2)
            sl.setSpacing(4)
            sw_btn = QtWidgets.QCheckBox("封禁")
            sw_btn.setChecked(bool(r["blocked"]))
            sw_btn.setStyleSheet("QCheckBox { spacing: 6px; }")
            sw_btn.stateChanged.connect(
                lambda st, exe=r["exe"]: _on_toggle(exe, st != 0, refresh, status_bar)
            )
            sl.addWidget(sw_btn)
            sl.addStretch(1)
            table.setCellWidget(i, 3, sw)
            # 首次出现 / 最近出现
            table.setItem(i, 4, QtWidgets.QTableWidgetItem(r["first_seen"]))
            table.setItem(i, 5, QtWidgets.QTableWidgetItem(r["last_seen"]))
            # 处置状态
            st_item = QtWidgets.QTableWidgetItem(HOST_STATUS_LABELS.get(r["status"], r["status"]))
            st_item.setForeground(QtGui.QColor(host_status_colors().get(r["status"], _p["text_secondary"])))
            table.setItem(i, 6, st_item)
            # 操作按钮：放行 / 拦截 / 删除
            cell = _log_action_buttons(r["exe"], _on_log_action)
            table.setCellWidget(i, 7, cell)
            # 行整行的 checkbox 也可用右键
            table.item(i, 0).setData(QtCore.Qt.UserRole, r["exe"])
        # 内容换行后按内容高度重排行高；cell widget 内按钮若仍超出行高则逐行抬高。
        # 真实检查：子按钮 sizeHint().height() + 容器上下边距 vs 当前行高
        # （旧实现比较容器 cell.geometry()，其恒等于行高，永远检测不到溢出）。
        table.resizeRowsToContents()
        default_h = _sz["webview_row_height"]
        for i in range(table.rowCount()):
            for c in range(table.columnCount()):
                cell = table.cellWidget(i, c)
                if cell is None:
                    continue
                btn_h = max((b.sizeHint().height()
                             for b in cell.findChildren(QtWidgets.QPushButton)), default=0)
                if btn_h <= 0:
                    continue
                margins = (cell.layout().contentsMargins()
                           if cell.layout() is not None else QtCore.QMargins())
                need = btn_h + margins.top() + margins.bottom()
                if need > table.rowHeight(i):
                    table.setRowHeight(i, max(default_h, need))
                    break

    def refresh():
        try:
            hosts = _ordered_hosts()
        except Exception as e:
            hosts = []
            status_bar.setText(f"扫描失败: {e}")
        _cached_hosts[:] = hosts
        total = len(hosts)
        blocked_count = sum(1 for h in hosts if h["blocked"])
        hidden = set(load_hidden_hosts(owner.context.config))
        hidden_n = len(hosts) - len(_visible_hosts(hosts, hidden))
        if hidden_n > 0:
            lb_count.setText(f"{total} 个程序 · 已封禁 {blocked_count} · 已隐藏 {hidden_n}")
        else:
            lb_count.setText(f"{total} 个程序 · 已封禁 {blocked_count}")
        if not hosts:
            status_bar.setText("暂未检测到使用 WebView2 的第三方程序")
        else:
            status_bar.setText("绿色=有网络连接 · 未运行=当前未启动 · 已拦截=封禁生效中（持续杀进程）")
        _populate()

    def _on_log_action(exe, action):
        try:
            owner.set_host_handler(exe, action)
        except Exception as e:
            status_bar.setText(f"操作失败: {e}")
        else:
            label = {"allow": "放行", "block": "拦截", "forget": "删除记录"}.get(action, action)
            status_bar.setText(f"已{label} {os.path.basename(exe)}")
        refresh()

    def _on_toggle(exe, blocked, refresh_fn, status_lbl):
        try:
            owner.set_host_blocked(exe, blocked)
        except Exception as e:
            status_lbl.setText(f"操作失败: {e}")
            refresh_fn()
            return
        if blocked:
            status_lbl.setText(f"已封禁 {os.path.basename(exe)}，其 WebView2 进程已被终止并持续拦截")
        else:
            status_lbl.setText(f"已放行 {os.path.basename(exe)}")
        refresh_fn()

    table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def _on_unhide(exe):
        hidden = load_hidden_hosts(owner.context.config)
        if exe in hidden:
            hidden.remove(exe)
            save_hidden_hosts(owner.context.config, hidden)
        refresh()

    def _open_hidden_dialog():
        hidden = load_hidden_hosts(owner.context.config)
        if hidden:
            show_hidden_dialog(w, hidden, _on_unhide)

    def _on_header_clicked(col):
        nonlocal _sort_col, _sort_order
        key = _SORTABLE_COLUMNS.get(col)
        if key is None:
            return
        if _sort_col == key:
            _sort_order = "desc" if _sort_order == "asc" else "asc"
        else:
            _sort_col = key
            _sort_order = "asc"
        header = table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(
            col,
            QtCore.Qt.AscendingOrder if _sort_order == "asc" else QtCore.Qt.DescendingOrder)
        _populate()

    def _menu(pos):
        row = table.rowAt(pos.y())
        hidden = load_hidden_hosts(owner.context.config)

        if row < 0:
            if hidden:
                menu = QtWidgets.QMenu()
                act_restore = menu.addAction("恢复显示（显示所有隐藏项）")
                action = menu.exec_(table.mapToGlobal(pos))
                if action == act_restore:
                    _open_hidden_dialog()
            return
        exe = table.item(row, 0).data(QtCore.Qt.UserRole) if table.item(row, 0) else None
        if not exe:
            return
        menu = QtWidgets.QMenu()
        act = menu.addAction("打开文件位置")
        act2 = menu.addAction("结束该程序的 WebView2 进程")
        if exe in set(owner.blocked):
            act3 = menu.addAction("放行")
        else:
            act3 = menu.addAction("封禁")
        act_hide = None
        if exe not in hidden:
            act_hide = menu.addAction("隐藏此程序")
        act_restore = None
        if hidden:
            act_restore = menu.addAction("恢复显示（显示所有隐藏项）")
        action = menu.exec_(table.mapToGlobal(pos))
        if action == act:
            import subprocess
            try:
                subprocess.Popen(["explorer", "/select,", exe])
            except Exception:
                pass
        elif action == act2:
            n = len(kill_host_webview([exe]))
            status_bar.setText(f"已结束 {n} 个 WebView2 进程")
        elif action == act3:
            blocked = exe in set(owner.blocked)
            _on_toggle(exe, not blocked, refresh, status_bar)
        elif act_hide is not None and action == act_hide:
            hidden.append(exe)
            save_hidden_hosts(owner.context.config, hidden)
            refresh()
        elif act_restore is not None and action == act_restore:
            _open_hidden_dialog()

    table.customContextMenuRequested.connect(_menu)

    btn_refresh.clicked.connect(refresh)
    _log_view_combo.currentIndexChanged.connect(_populate)
    _blocked_combo.currentIndexChanged.connect(_populate)
    _search_input.textChanged.connect(_populate)
    _search_input.returnPressed.connect(_populate)
    table.horizontalHeader().sectionClicked.connect(_on_header_clicked)
    btn_hidden.clicked.connect(_open_hidden_dialog)
    refresh()
    owner._page_refresh = refresh
    return w