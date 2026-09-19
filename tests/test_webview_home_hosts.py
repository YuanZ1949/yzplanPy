"""webview_control 主页「实时宿主列表」行为测试。

背景（主页问题反馈）：主页此前只显示一行统计文本（第三方程序 N 个 | 已封禁 N 个）
+ 两个全量按钮，没有宿主级信息。用户选择「实时宿主列表」形态：
- 列出当前正在用 WebView2 的第三方程序：名称/状态/WebView 实例数/连接数
- 每行带 拦截/放行 按钮（走 owner.set_host_blocked）
- 顶部保留 全部拦截/全部放行 全量按钮

锁定的主页行为：
1. 有宿主数据时列表渲染每行（名称 + 实例数 + 连接数）
2. 未运行/空数据时显示空态文本而非崩溃
3. 每行有拦截/放行按钮，点击调用 owner.set_host_blocked
4. 全量按钮保留；状态行保留
"""
import pytest
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _Owner:
    """webview 主页引用的 owner 属性/方法最小替身。"""

    def __init__(self, hosts=None, blocked=None):
        self.context = None
        self._last_hosts = hosts or []
        self._monitor_running = True
        self.blocked = set(blocked or [])
        self.host_log = []
        self._home_refresh = None
        self._set_calls = []

    def set_host_blocked(self, host_exe, blocked):
        self._set_calls.append((host_exe, bool(blocked)))
        if blocked:
            self.blocked.add(host_exe)
        else:
            self.blocked.discard(host_exe)
        return bool(blocked)


def _sample_hosts():
    return [
        {
            "exe": r"C:\app\notion.exe",
            "name": "notion",
            "running": True,
            "procs": [1234],
            "webview_count": 3,
            "connections": 5,
            "blocked": False,
            "user_data_dirs": ["udd1"],
        },
        {
            "exe": r"C:\game\launcher.exe",
            "name": "launcher",
            "running": True,
            "procs": [5678],
            "webview_count": 1,
            "connections": 0,
            "blocked": True,
            "user_data_dirs": ["udd2"],
        },
    ]


def _make_home(hosts=None, blocked=None, running=True):
    from modules.webview_control.home import _make_home_widget
    owner = _Owner(hosts=hosts, blocked=blocked)
    owner._monitor_running = running
    w = _make_home_widget(owner, None)
    w.resize(360, 320)
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return owner, w


def _host_rows(w):
    """主页列表中的宿主行容器列表。"""
    rows = getattr(w, "_host_rows", None)
    if rows is None:
        # 结构未知时给出失败信息便于诊断
        children = [type(c).__name__ for c in w.findChildren(QtWidgets.QWidget)]
        pytest.fail(f"未找到 w._host_rows 宿主行集合，主页子控件: {children}")
    return rows


# ── 1. 宿主列表渲染 ────────────────────────────────────────────────

def test_home_lists_hosts_with_counts():
    """主页应逐行列出宿主：名称 + WebView 实例数 + 连接数。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts())
    try:
        rows = _host_rows(w)
        assert len(rows) == 2, f"两个宿主应渲染两行，实际 {len(rows)}"
        texts = []
        for r in rows:
            texts.extend(lb.text() for lb in r.findChildren(QtWidgets.QLabel))
        joined = " | ".join(texts)
        assert "notion" in joined, f"应显示宿主名 notion，实际文本: {joined}"
        assert "launcher" in joined, f"应显示宿主名 launcher，实际文本: {joined}"
        assert "3" in joined, "应显示 WebView 实例数"
        assert "5" in joined, "应显示连接数"
    finally:
        w.close()


def test_home_shows_blocked_state():
    """已封禁宿主行应有封禁状态标识。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts(), blocked=[r"C:\game\launcher.exe"])
    try:
        rows = _host_rows(w)
        launcher = rows[1] if "launcher" in _row_text(rows[1]) else rows[0]
        texts = _row_text(launcher)
        assert any(k in texts for k in ("封禁", "拦截")), \
            f"已封禁宿主行应有状态标识，实际: {texts}"
    finally:
        w.close()


def _row_text(row):
    return " | ".join(lb.text() for lb in row.findChildren(QtWidgets.QLabel))


# ── 2. 每行 拦截/放行 按钮 ──────────────────────────────────────────

def test_home_row_has_block_unblock_buttons():
    """每行应含 拦截 与 放行 按钮（QPushButton，文本匹配）。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts())
    try:
        rows = _host_rows(w)
        for r in rows:
            btns = [b for b in r.findChildren(QtWidgets.QPushButton)]
            labels = [b.text() for b in btns]
            assert any(lb in ("拦截", "放行") for lb in labels), \
                f"每行应含 拦截/放行 按钮，实际: {labels}"
    finally:
        w.close()


def test_row_block_button_calls_owner(monkeypatch):
    """点击行内「拦截」→ owner.set_host_blocked(exe, True) 被调用。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts())
    try:
        rows = _host_rows(w)
        btn = next(b for b in rows[0].findChildren(QtWidgets.QPushButton)
                   if b.text() == "拦截")
        btn.click()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert owner._set_calls, f"点击拦截应调用 set_host_blocked，实际: {owner._set_calls}"
        exe, blocked = owner._set_calls[0]
        assert blocked is True, f"拦截应传 blocked=True，实际: {blocked}"
        assert exe == r"C:\app\notion.exe", f"应传入对应宿主 exe，实际: {exe}"
    finally:
        w.close()


def test_row_unblock_button_calls_owner():
    """点击行内「放行」→ owner.set_host_blocked(exe, False)。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts(),
                          blocked=[r"C:\game\launcher.exe"])
    try:
        rows = _host_rows(w)
        launcher = next(r for r in rows if "launcher" in _row_text(r))
        btn = next(b for b in launcher.findChildren(QtWidgets.QPushButton)
                   if b.text() == "放行")
        btn.click()
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert owner._set_calls, "点击放行应调用 set_host_blocked"
        exe, blocked = owner._set_calls[0]
        assert blocked is False, f"放行应传 blocked=False，实际: {blocked}"
        assert exe == r"C:\game\launcher.exe"
    finally:
        w.close()


# ── 3. 全量按钮 & 状态行保留 ────────────────────────────────────────

def test_home_keeps_global_buttons_and_status():
    """顶部 全部拦截/全部放行 与状态行保留。"""
    _app()
    owner, w = _make_home(hosts=_sample_hosts())
    try:
        all_btns = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
        assert "全部拦截" in all_btns, f"应保留全部拦截按钮，实际: {all_btns}"
        assert "全部放行" in all_btns, f"应保留全部放行按钮，实际: {all_btns}"
        labels = [lb.text() for lb in w.findChildren(QtWidgets.QLabel)]
        assert any("第三方程序" in t for t in labels), \
            f"状态行应保留统计文本，实际: {labels}"
    finally:
        w.close()


def test_home_empty_state_text():
    """无宿主（扫描空）→ 显示空态文本不崩溃。"""
    _app()
    owner, w = _make_home(hosts=[])
    try:
        labels = [lb.text() for lb in w.findChildren(QtWidgets.QLabel)]
        assert any("第三方程序: 0 个" in t for t in labels), \
            f"空态应保留统计文本，实际: {labels}"
        # 不应渲染任何宿主行
        assert len(_host_rows(w)) == 0
    finally:
        w.close()