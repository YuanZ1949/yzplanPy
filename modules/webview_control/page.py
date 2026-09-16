"""webview_control - full page widget."""
import os
import time
from core.theme.tokens import sizing, theme_palette
from .hosts import kill_host_webview, scan_hosts
from .constants import HOST_STATUS_LABELS, host_status_colors
from .config import load_hidden_hosts, save_hidden_hosts
from .hidden_dialog import _visible_hosts, show_hidden_dialog

def _log_action_buttons(exe, on_action, sz):
    """组装 放行/拦截/删除 三个操作按钮，返回承载 QWidget。

    on_action: callable(exe_str, action_str)，action ∈ {"allow","block","forget"}。
    """
    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    from qfluentwidgets import PushButton

    cell = QtWidgets.QWidget()
    hl = QtWidgets.QHBoxLayout(cell)
    hl.setContentsMargins(6, 2, 6, 2)
    hl.setSpacing(4)
    btn_allow = PushButton("放行")
    btn_block = PushButton("拦截")
    btn_forget = PushButton("删除")
    for b in (btn_allow, btn_block, btn_forget):
        # 最小宽度保证窗口缩小时按钮文字（放行/拦截/删除）完整显示；
        # 高度 30px 匹配主题 padding(5px+5px)+文字高度，避免文字被纵向裁剪
        b.setMinimumWidth(56)
        b.setFixedHeight(sz["input_height"])
    btn_allow.clicked.connect(lambda _=False, e=exe: on_action(e, "allow"))
    btn_block.clicked.connect(lambda _=False, e=exe: on_action(e, "block"))
    btn_forget.clicked.connect(lambda _=False, e=exe: on_action(e, "forget"))
    hl.addWidget(btn_allow)
    hl.addWidget(btn_block)
    hl.addWidget(btn_forget)
    hl.addStretch(1)
    return cell

def _pending_entries(entries, view):
    """按视图过滤拦截记录：pending=仅待处置 / done=仅已处置 / all=全部。"""
    if view == "pending":
        return [e for e in entries if e.get("status") == "pending"]
    if view == "done":
        return [e for e in entries if e.get("status") != "pending"]
    return list(entries)

def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, ComboBox, PushButton, StrongBodyLabel

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
    lay.addLayout(toolbar)

    # ── 处置状态视图过滤（待处置/已处置/全部） ──────────────────────
    filter_row = QtWidgets.QHBoxLayout()
    filter_row.setSpacing(8)
    filter_label = StrongBodyLabel("处置状态", w)
    filter_row.addWidget(filter_label)
    _log_view_combo = ComboBox()
    for label, value in (("待处置", "pending"), ("已处置", "done"), ("全部", "all")):
        _log_view_combo.addItem(label, userData=value)
    _log_view_combo.setCurrentIndex(0)   # 默认待处置
    filter_row.addWidget(_log_view_combo)
    filter_row.addStretch(1)
    lay.addLayout(filter_row)

    # ── 合并表：一行 = 一个程序（实时扫描 + 拦截记录） ───────────────
    table = QtWidgets.QTableWidget()
    table.setColumnCount(8)
    table.setHorizontalHeaderLabels(
        ["程序名", "程序地址", "链接状态", "封禁开关",
         "首次出现", "最近出现", "处置状态", "操作"])
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(table, width_caps={1: 0.35},
                        min_widths={3: 90, 4: 110, 5: 110, 6: 70, 7: 200})
    table.verticalHeader().setDefaultSectionSize(30)
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
            cell = _log_action_buttons(r["exe"], _on_log_action, _sz)
            table.setCellWidget(i, 7, cell)
            # 行整行的 checkbox 也可用右键
            table.item(i, 0).setData(QtCore.Qt.UserRole, r["exe"])

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

    def _menu(pos):
        row = table.rowAt(pos.y())
        hidden = load_hidden_hosts(owner.context.config)

        def _on_unhide(exe):
            if exe in hidden:
                hidden.remove(exe)
                save_hidden_hosts(owner.context.config, hidden)
            refresh()

        if row < 0:
            if hidden:
                menu = QtWidgets.QMenu()
                act_restore = menu.addAction("恢复显示（显示所有隐藏项）")
                action = menu.exec_(table.mapToGlobal(pos))
                if action == act_restore:
                    show_hidden_dialog(w, hidden, _on_unhide)
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
            show_hidden_dialog(w, hidden, _on_unhide)

    table.customContextMenuRequested.connect(_menu)

    btn_refresh.clicked.connect(refresh)
    _log_view_combo.currentIndexChanged.connect(_populate)
    refresh()
    owner._page_refresh = refresh
    return w