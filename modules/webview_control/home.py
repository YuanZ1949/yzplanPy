"""webview_control - home widget."""
import os
from .hosts import scan_hosts

def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 6)
    lay.setSpacing(4)

    title = StrongBodyLabel("WebView2 管控")
    lay.addWidget(title)

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

    def refresh():
        try:
            hosts = owner._last_hosts if owner._monitor_running else scan_hosts(owner.blocked)
            blocked = sum(1 for h in hosts if blocked_host(h["exe"], owner.blocked))
            lines = [
                f"第三方程序: {len(hosts)} 个",
                f"已封禁: {len(owner.blocked)} 个",
            ]
            status_lbl.setText(" | ".join(lines))
        except Exception as e:
            status_lbl.setText(f"刷新失败: {e}")

    refresh()
    owner._home_refresh = refresh
    return w


def blocked_host(exe, blocked):
    return os.path.normcase(exe).lower() in set(blocked or [])


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
