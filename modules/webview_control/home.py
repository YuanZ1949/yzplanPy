"""webview_control - home widget."""
import os
from .hosts import scan_hosts


def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 6)
    lay.setSpacing(4)

    status_lbl = BodyLabel("加载中...")
    status_lbl.setWordWrap(True)
    lay.addWidget(status_lbl)

    btn_row = QtWidgets.QHBoxLayout()
    btn_block = PrimaryPushButton("全部拦截")
    btn_unblock = PushButton("全部放行")
    # 窄窗口下按钮文字不被截断：最小宽度 + 水平扩展均分剩余空间
    for _b in (btn_block, btn_unblock):
        _b.setMinimumWidth(80)
        _b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    btn_block.clicked.connect(lambda: _quick_block_all(owner, status_lbl))
    btn_unblock.clicked.connect(lambda: _quick_unblock_all(owner, status_lbl))
    btn_row.addWidget(btn_block)
    btn_row.addWidget(btn_unblock)
    lay.addLayout(btn_row)

    # 宿主行容器：refresh 时重建 _host_rows
    host_lay = QtWidgets.QVBoxLayout()
    host_lay.setSpacing(2)
    lay.addLayout(host_lay, 1)
    w._host_rows = []

    def clear_host_rows():
        while host_lay.count():
            item = host_lay.takeAt(0)
            row = item.widget()
            if row is not None:
                row.deleteLater()
        w._host_rows = []

    def refresh():
        try:
            hosts = owner._last_hosts if owner._monitor_running else scan_hosts(owner.blocked)
            status_lbl.setText(f"第三方程序: {len(hosts)} 个 | 已封禁: {len(owner.blocked)} 个")
            clear_host_rows()
            for h in hosts:
                row = _make_host_row(h, owner)
                host_lay.addWidget(row)
                w._host_rows.append(row)
        except Exception as e:
            status_lbl.setText(f"刷新失败: {e}")

    refresh()
    owner._home_refresh = refresh
    return w


def _make_host_row(host, owner):
    """单宿主行：名称 + 实例/连接数 + 拦截·放行按钮。"""
    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    from ui.widgets import make_button, make_label

    row = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(row)
    lay.setContentsMargins(2, 2, 2, 2)
    lay.setSpacing(6)

    blk = blocked_host(host["exe"], owner.blocked)
    name_lbl = make_label(host.get("name") or host["exe"], role="body")
    detail = f"{host['webview_count']} 实例 | {host['connections']} 连接"
    if blk:
        detail += " · 已封禁"
    detail_lbl = make_label(detail, role="caption")

    lay.addWidget(name_lbl)
    lay.addWidget(detail_lbl)
    lay.addStretch(1)

    btn_block = make_button("拦截", kind="danger", size="sm")
    btn_unblock = make_button("放行", size="sm")
    btn_block.clicked.connect(lambda: owner.set_host_blocked(host["exe"], True))
    btn_unblock.clicked.connect(lambda: owner.set_host_blocked(host["exe"], False))
    lay.addWidget(btn_unblock)
    lay.addWidget(btn_block)
    return row


def blocked_host(exe, blocked):
    norm = {os.path.normcase(b).lower() for b in (blocked or [])}
    return os.path.normcase(exe).lower() in norm


def _quick_block_all(owner, status_lbl):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()
    try:
        hosts = scan_hosts(owner.blocked)
        exes = [h["exe"] for h in hosts]
        if not exes:
            status_lbl.setText("未检测到使用 WebView2 的第三方程序")
            return
        for exe in exes:
            owner.set_host_blocked(exe, True)
        status_lbl.setText(f"已封禁 {len(exes)} 个程序，并已终止其 WebView2 进程")
        owner._home_refresh()
    except Exception as e:
        status_lbl.setText(f"操作失败: {e}")


def _quick_unblock_all(owner, status_lbl):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, _ = import_qt()
    try:
        exes = list(owner.blocked)
        if not exes:
            status_lbl.setText("当前没有已封禁的程序")
            return
        for exe in exes:
            owner.set_host_blocked(exe, False)
        status_lbl.setText(f"已放行 {len(exes)} 个程序")
        owner._home_refresh()
    except Exception as e:
        status_lbl.setText(f"操作失败: {e}")