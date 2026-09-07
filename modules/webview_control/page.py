"""webview_control - full page widget."""
import os
from .hosts import kill_host_webview, scan_hosts
from .constants import HOST_STATUS_LABELS, HOST_STATUS_COLORS

def _make_page_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    desc = BodyLabel(
        "这里列出使用 WebView2 的第三方程序。封禁后会自动终止该程序的 WebView2 子进程，"
        "并在其后台持续拦截（程序重新打开 WebView2 也会被立即终止）。", w)
    desc.setWordWrap(True)
    desc.setStyleSheet("color: #888;")
    lay.addWidget(desc)

    toolbar = QtWidgets.QHBoxLayout()
    btn_refresh = PushButton("刷新")
    lb_count = BodyLabel("")
    lb_count.setStyleSheet("color: #888;")
    toolbar.addWidget(btn_refresh)
    toolbar.addWidget(lb_count)
    toolbar.addStretch(1)
    lay.addLayout(toolbar)

    table = QtWidgets.QTableWidget()
    table.setColumnCount(4)
    table.setHorizontalHeaderLabels(["程序名", "程序地址", "链接状态", "封禁开关"])
    from ui.adaptive_table import make_adaptive_table
    make_adaptive_table(table)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    lay.addWidget(table, 2)

    # ── 拦截记录（未决宿主可回溯处置） ──────────────────────────
    log_label = StrongBodyLabel("拦截记录", w)
    lay.addWidget(log_label)

    log_table = QtWidgets.QTableWidget()
    log_table.setColumnCount(5)
    log_table.setHorizontalHeaderLabels(["程序名", "首次出现", "最近出现", "状态", "操作"])
    make_adaptive_table(log_table)
    log_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    log_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    log_table.setAlternatingRowColors(True)
    log_table.verticalHeader().setVisible(False)
    log_table.setStyleSheet(
        "QTableWidget { border: none; background: transparent; gridline-color: rgba(128,128,128,0.1); }"
        "QTableWidget::item { selection-background-color: rgba(128,128,128,0.15); }")
    lay.addWidget(log_table, 1)

    status_bar = BodyLabel("")
    status_bar.setStyleSheet("color: #888;")
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

    def refresh():
        try:
            hosts = _ordered_hosts()
        except Exception as e:
            hosts = []
            status_bar.setText(f"扫描失败: {e}")
        total = len(hosts)
        blocked_count = sum(1 for h in hosts if h["blocked"])
        lb_count.setText(f"{total} 个程序 · 已封禁 {blocked_count}")
        table.setRowCount(len(hosts))
        for i, h in enumerate(hosts):
            # 程序名
            name_item = QtWidgets.QTableWidgetItem(h["name"])
            table.setItem(i, 0, name_item)
            # 程序地址
            table.setItem(i, 1, QtWidgets.QTableWidgetItem(h["exe"]))
            # 链接状态
            if h["blocked"]:
                link_item = QtWidgets.QTableWidgetItem("已拦截")
                link_item.setForeground(QtGui.QColor("#e74c3c"))
            elif not h["running"]:
                link_item = QtWidgets.QTableWidgetItem("未运行")
                link_item.setForeground(QtGui.QColor("#888"))
            elif h["connections"] > 0:
                link_item = QtWidgets.QTableWidgetItem(f"连接中 ({h['connections']} 连接)")
                link_item.setForeground(QtGui.QColor("#27ae60"))
            else:
                link_item = QtWidgets.QTableWidgetItem("运行中·无连接")
                link_item.setForeground(QtGui.QColor("#888"))
            table.setItem(i, 2, link_item)
            # 封禁开关
            sw = QtWidgets.QWidget()
            sl = QtWidgets.QHBoxLayout(sw)
            sl.setContentsMargins(6, 2, 6, 2)
            sl.setSpacing(4)
            sw_btn = QtWidgets.QCheckBox("封禁")
            sw_btn.setChecked(bool(h["blocked"]))
            sw_btn.setStyleSheet("QCheckBox { spacing: 6px; }")
            sw_btn.stateChanged.connect(
                lambda st, exe=h["exe"]: _on_toggle(exe, st != 0, refresh, status_bar)
            )
            sl.addWidget(sw_btn)
            sl.addStretch(1)
            table.setCellWidget(i, 3, sw)
            # 行整行的 checkbox 也可用右键
            table.item(i, 0).setData(QtCore.Qt.UserRole, h["exe"])
        if not hosts:
            status_bar.setText("暂未检测到使用 WebView2 的第三方程序")
        else:
            status_bar.setText("绿色=有网络连接 · 未运行=当前未启动 · 已拦截=封禁生效中（持续杀进程）")
        refresh_log()

    def refresh_log():
        entries = sorted(owner.host_log, key=lambda e: e.get("last_seen", ""), reverse=True)
        log_table.setRowCount(len(entries))
        for i, ent in enumerate(entries):
            log_table.setItem(i, 0, QtWidgets.QTableWidgetItem(ent["name"]))
            log_table.setItem(i, 1, QtWidgets.QTableWidgetItem(ent.get("first_seen", "")))
            log_table.setItem(i, 2, QtWidgets.QTableWidgetItem(ent.get("last_seen", "")))
            st_item = QtWidgets.QTableWidgetItem(HOST_STATUS_LABELS.get(ent["status"], ent["status"]))
            st_item.setForeground(QtGui.QColor(HOST_STATUS_COLORS.get(ent["status"], "#888")))
            log_table.setItem(i, 3, st_item)
            # 操作按钮：放行 / 拦截 / 删除
            cell = QtWidgets.QWidget()
            hl = QtWidgets.QHBoxLayout(cell)
            hl.setContentsMargins(6, 2, 6, 2)
            hl.setSpacing(4)
            btn_allow = PushButton("放行")
            btn_block = PushButton("拦截")
            btn_forget = PushButton("删除")
            for b in (btn_allow, btn_block, btn_forget):
                b.setFixedHeight(26)
            exe = ent["exe"]
            btn_allow.clicked.connect(lambda _=False, e=exe: _on_log_action(e, "allow"))
            btn_block.clicked.connect(lambda _=False, e=exe: _on_log_action(e, "block"))
            btn_forget.clicked.connect(lambda _=False, e=exe: _on_log_action(e, "forget"))
            hl.addWidget(btn_allow)
            hl.addWidget(btn_block)
            hl.addWidget(btn_forget)
            hl.addStretch(1)
            log_table.setCellWidget(i, 4, cell)

    def _on_log_action(exe, action):
        try:
            owner.set_host_handler(exe, action)
        except Exception as e:
            status_bar.setText(f"操作失败: {e}")
        else:
            label = {"allow": "放行", "block": "拦截", "forget": "删除记录"}.get(action, action)
            status_bar.setText(f"已{label} {os.path.basename(exe)}")
        refresh()
        refresh_log()

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
        if row < 0:
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

    table.customContextMenuRequested.connect(_menu)

    btn_refresh.clicked.connect(refresh)
    refresh()
    owner._page_refresh = refresh
    return w
