"""webview_control merged table: search / sort / blocked filter / hidden entry.

Covers Task 14: 合并单表加 搜索 + 点表头排序 + 封禁筛选 + 隐藏项入口。

验证点:
- 纯函数: _search_entries 命中程序名与地址、大小写不敏感、空关键词返回全部
- 纯函数: _blocked_entries 按 blocked 过滤（blocked/unblocked/all）
- 纯函数: _sort_entries 按 name/first_seen/status 排序，时间按真实值而非字符串
- UI: 搜索框实时过滤（命中 name 与 exe），无命中 → 空表
- UI: 点「首次出现」表头 → 按真实时间升/降序
- UI: 封禁筛选只留已封禁/未封禁行
- UI: 处置状态 + 封禁 + 关键词三者叠加
- UI: 排序后操作按钮仍与正确程序绑定（点放行/拦截断言对应 exe 变更）
- UI: 「隐藏项」按钮打开「显示所有隐藏项」对话框
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import import_qt

_, QtCore, _, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication

from modules.webview_control.page import (
    _blocked_entries,
    _search_entries,
    _sort_entries,
    _time_sort_key,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _norm(p):
    return os.path.normcase(p).lower()


class _FakeConfig:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):
        pass


class _FakeContext:
    def __init__(self, config):
        self.config = config


def _make_page(scan_data, host_log_data, blocked=None, hidden=None, monkeypatch=None):
    """Helper: build the merged webview page with controlled scan + log data."""
    from modules.webview_control.module import Module

    _app()

    cfg = _FakeConfig()
    if blocked:
        cfg.data["webview"] = {"blocked_hosts": sorted(blocked)}
    if hidden:
        cfg.data.setdefault("webview", {})["hidden_hosts"] = hidden

    mod = Module(_FakeContext(cfg))
    mod.host_log = list(host_log_data)

    import modules.webview_control.page as page_mod
    if monkeypatch is not None:
        monkeypatch.setattr(page_mod, "scan_hosts", lambda blocked: list(scan_data))
    else:
        _orig_scan = page_mod.scan_hosts
        page_mod.scan_hosts = lambda blocked: list(scan_data)

    page = mod.create_page(None)
    if monkeypatch is None:
        page_mod.scan_hosts = _orig_scan

    page.resize(900, 600)
    page.show()
    for _ in range(5):
        QApplication.processEvents()
        QtCore.QThread.msleep(20)

    return mod, page


def _table(page):
    return page.findChildren(QtWidgets.QTableWidget)[0]


def _search_input(page):
    return page.findChildren(QtWidgets.QLineEdit)[0]


def _blocked_combo(page):
    return next(c for c in page.findChildren(QtWidgets.QComboBox)
                if c.itemText(0) == "已封禁")


def _status_combo(page):
    from qfluentwidgets import ComboBox
    return page.findChildren(ComboBox)[0]


def _pump():
    for _ in range(3):
        QApplication.processEvents()


# ── 纯函数: 搜索 ────────────────────────────────────────────────────────

def test_search_entries_matches_name_and_exe():
    entries = [
        {"exe": r"C:\Apps\WeChat.exe", "name": "WeChat"},
        {"exe": r"C:\Apps\Tencent\QQ.exe", "name": "QQ"},
    ]
    # 关键词同时命中程序名与地址
    assert [e["name"] for e in _search_entries(entries, "wechat")] == ["WeChat"]
    # 只命中地址
    assert [e["name"] for e in _search_entries(entries, "tencent")] == ["QQ"]
    # 只命中名称
    assert [e["name"] for e in _search_entries(entries, "qq")] == ["QQ"]


def test_search_entries_no_match_returns_empty():
    entries = [{"exe": r"C:\Apps\A.exe", "name": "A"}]
    assert _search_entries(entries, "zzz_no_such") == []
    # 空/空白关键词 → 全部
    assert _search_entries(entries, "") == entries
    assert _search_entries(entries, "   ") == entries


def test_search_entries_case_insensitive():
    entries = [{"exe": r"C:\Apps\WeChat.exe", "name": "WeChat"}]
    assert _search_entries(entries, "WECHAT") == entries
    assert _search_entries(entries, "wechat") == entries
    assert _search_entries(entries, "WeChat") == entries


# ── 纯函数: 封禁筛选 ────────────────────────────────────────────────────

def test_blocked_entries_filters():
    entries = [
        {"exe": r"C:\Apps\A.exe", "blocked": True},
        {"exe": r"C:\Apps\B.exe", "blocked": False},
        {"exe": r"C:\Apps\C.exe"},  # 缺 blocked 键 → 视为未封禁
    ]
    assert [e["exe"] for e in _blocked_entries(entries, "blocked")] == [r"C:\Apps\A.exe"]
    assert [e["exe"] for e in _blocked_entries(entries, "unblocked")] == [
        r"C:\Apps\B.exe", r"C:\Apps\C.exe"]
    assert _blocked_entries(entries, "all") == entries


# ── 纯函数: 排序 ────────────────────────────────────────────────────────

def test_sort_entries_by_name():
    rows = [
        {"exe": r"C:\Apps\B.exe", "name": "Beta"},
        {"exe": r"C:\Apps\A.exe", "name": "Alpha"},
        {"exe": r"C:\Apps\C.exe", "name": "Charlie"},
    ]
    got = _sort_entries(rows, "name", "asc")
    assert [r["name"] for r in got] == ["Alpha", "Beta", "Charlie"]
    got = _sort_entries(rows, "name", "desc")
    assert [r["name"] for r in got] == ["Charlie", "Beta", "Alpha"]


def test_sort_entries_by_first_seen_uses_real_time():
    """时间排序必须按真实时间，而非字符串比较。

    "2026-01-10 00:00:00"（1月10日）字符串序在 "2026-1-2 00:00:00"（1月2日）之前，
    但真实时间 1月2日 更早 → 升序应为 B, A。
    """
    rows = [
        {"exe": r"C:\Apps\A.exe", "name": "A", "first_seen": "2026-01-10 00:00:00"},
        {"exe": r"C:\Apps\B.exe", "name": "B", "first_seen": "2026-1-2 00:00:00"},
    ]
    got = _sort_entries(rows, "first_seen", "asc")
    assert [r["exe"] for r in got] == [r"C:\Apps\B.exe", r"C:\Apps\A.exe"]


def test_sort_entries_by_status_rank():
    rows = [
        {"exe": r"C:\Apps\A.exe", "status": "blocked"},
        {"exe": r"C:\Apps\B.exe", "status": "pending"},
        {"exe": r"C:\Apps\C.exe", "status": "allowed"},
    ]
    got = _sort_entries(rows, "status", "asc")
    assert [r["status"] for r in got] == ["pending", "allowed", "blocked"]


def test_sort_entries_unknown_key_returns_copy():
    rows = [{"exe": r"C:\Apps\A.exe", "name": "A"}]
    got = _sort_entries(rows, "bogus", "asc")
    assert got == rows
    assert got is not rows


def test_time_sort_key_parses_real_time():
    assert _time_sort_key("2026-01-02 00:00:00") > _time_sort_key("2026-01-01 00:00:00")
    # 仅日期 == 当日零点
    assert _time_sort_key("2026-01-01") == _time_sort_key("2026-01-01 00:00:00")
    # 非补零月份/日期也能解析
    assert _time_sort_key("2026-1-2 00:00:00") == _time_sort_key("2026-01-02 00:00:00")
    # 无法解析 → 0.0（排最前）
    assert _time_sort_key("") == 0.0
    assert _time_sort_key("garbage") == 0.0


# ── UI: 搜索 ────────────────────────────────────────────────────────────

def test_search_input_filters_by_name_and_exe(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\WeChat.exe"), "name": "WeChat", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\Tencent\QQ.exe"), "name": "QQ", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 2  # 默认 pending 视图：两个都 pending

    search = _search_input(page)
    # 关键词同时命中程序名与地址（wechat 同时是 name 与 exe 的一部分）
    search.setText("wechat")
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "WeChat"
    # 只命中地址
    search.setText("tencent")
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "QQ"
    # 只命中名称
    search.setText("qq")
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "QQ"
    # 清空 → 恢复全部
    search.setText("")
    _pump()
    assert table.rowCount() == 2

    page.close()
    page.deleteLater()


def test_search_no_match_empties_table(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 2

    _search_input(page).setText("zzz_no_such_program")
    _pump()
    assert table.rowCount() == 0

    page.close()
    page.deleteLater()


# ── UI: 表头排序 ────────────────────────────────────────────────────────

def test_click_first_seen_header_sorts_by_real_time(monkeypatch):
    host_log_data = [
        {"exe": _norm(r"C:\Apps\C.exe"), "name": "C",
         "first_seen": "2026-03-01 08:00:00", "last_seen": "2026-03-01 08:00:00",
         "status": "pending"},
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A",
         "first_seen": "2025-01-01 00:00:00", "last_seen": "2025-01-01 00:00:00",
         "status": "pending"},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B",
         "first_seen": "2026-01-15 12:30:00", "last_seen": "2026-01-15 12:30:00",
         "status": "pending"},
    ]
    _, page = _make_page(scan_data=[], host_log_data=host_log_data, monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 3

    header = table.horizontalHeader()
    # 点「首次出现」表头 → 升序
    header.sectionClicked.emit(4)
    _pump()
    times = [table.item(r, 4).text() for r in range(table.rowCount())]
    assert times == ["2025-01-01 00:00:00", "2026-01-15 12:30:00", "2026-03-01 08:00:00"]
    # 再点一次 → 降序
    header.sectionClicked.emit(4)
    _pump()
    times = [table.item(r, 4).text() for r in range(table.rowCount())]
    assert times == ["2026-03-01 08:00:00", "2026-01-15 12:30:00", "2025-01-01 00:00:00"]

    page.close()
    page.deleteLater()


def test_click_name_header_sorts_by_name(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "Beta", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "Alpha", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 2

    header = table.horizontalHeader()
    header.sectionClicked.emit(0)
    _pump()
    names = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert names == ["Alpha", "Beta"]

    page.close()
    page.deleteLater()


# ── UI: 封禁筛选 ────────────────────────────────────────────────────────

def test_blocked_filter_only_blocked_rows(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": True,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = _table(page)
    # 默认 pending 视图：A 已封禁（无 host_log → status=blocked）不在 pending；B 显示
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "B"

    # 切到「全部」视图 → 2 行
    _status_combo(page).setCurrentIndex(2)
    _pump()
    assert table.rowCount() == 2

    # 封禁筛选 = 已封禁 → 只剩 A
    blocked_combo = _blocked_combo(page)
    blocked_combo.setCurrentIndex(0)
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "A"
    # 未封禁 → 只剩 B
    blocked_combo.setCurrentIndex(1)
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "B"
    # 全部 → 2 行
    blocked_combo.setCurrentIndex(2)
    _pump()
    assert table.rowCount() == 2

    page.close()
    page.deleteLater()


# ── UI: 三者叠加 ────────────────────────────────────────────────────────

def test_combined_status_blocked_keyword_filters(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "Alpha", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "Beta", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": True,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\C.exe"), "name": "Gamma", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\D.exe"), "name": "Delta", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": True,
         "user_data_dirs": []},
    ]
    host_log_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "Alpha",
         "first_seen": "2026-01-01", "last_seen": "2026-01-01", "status": "pending"},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "Beta",
         "first_seen": "2026-01-01", "last_seen": "2026-01-01", "status": "pending"},
        {"exe": _norm(r"C:\Apps\C.exe"), "name": "Gamma",
         "first_seen": "2026-01-01", "last_seen": "2026-01-01", "status": "allowed"},
        {"exe": _norm(r"C:\Apps\D.exe"), "name": "Delta",
         "first_seen": "2026-01-01", "last_seen": "2026-01-01", "status": "blocked"},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=host_log_data,
                           monkeypatch=monkeypatch)
    table = _table(page)
    # 默认 pending 视图：A(pending), B(pending) → 2 行
    assert table.rowCount() == 2

    # 封禁筛选 = 已封禁 → 只剩 B（pending + blocked）
    blocked_combo = _blocked_combo(page)
    blocked_combo.setCurrentIndex(0)
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Beta"

    # 再加关键词 beta → 仍 B
    search = _search_input(page)
    search.setText("beta")
    _pump()
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Beta"

    # 关键词改为 alpha → 无交集（pending+blocked+alpha 不存在）→ 空
    search.setText("alpha")
    _pump()
    assert table.rowCount() == 0

    page.close()
    page.deleteLater()


# ── UI: 排序后按钮绑定 ──────────────────────────────────────────────────

def test_sort_keeps_action_buttons_bound(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\Charlie.exe"), "name": "Charlie", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\Alpha.exe"), "name": "Alpha", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\Beta.exe"), "name": "Beta", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    mod, page = _make_page(scan_data=scan_data, host_log_data=[], monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 3

    # 点「程序名」表头升序 → Alpha, Beta, Charlie
    header = table.horizontalHeader()
    header.sectionClicked.emit(0)
    _pump()
    names = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert names == ["Alpha", "Beta", "Charlie"]

    # 行 2 = Charlie：点「拦截」→ Charlie 被封禁
    cell = table.cellWidget(2, 7)
    btns = {b.text(): b for b in cell.findChildren(QtWidgets.QPushButton)}
    btns["拦截"].click()
    _pump()
    charlie_exe = _norm(r"C:\Apps\Charlie.exe")
    assert charlie_exe in mod.blocked
    # Charlie 已拦截 → 从 pending 视图消失；剩余 Alpha, Beta
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "Alpha"

    # 行 0 = Alpha：点「放行」→ Alpha 被放行
    cell = table.cellWidget(0, 7)
    btns = {b.text(): b for b in cell.findChildren(QtWidgets.QPushButton)}
    btns["放行"].click()
    _pump()
    alpha_exe = _norm(r"C:\Apps\Alpha.exe")
    ent = next(e for e in mod.host_log if e["exe"] == alpha_exe)
    assert ent["status"] == "allowed"

    page.close()
    page.deleteLater()


# ── UI: 隐藏项入口 ──────────────────────────────────────────────────────

def test_hidden_items_button_opens_dialog(monkeypatch):
    scan_data = [
        {"exe": _norm(r"C:\Apps\A.exe"), "name": "A", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
        {"exe": _norm(r"C:\Apps\B.exe"), "name": "B", "running": True,
         "procs": [], "webview_count": 1, "connections": 0, "blocked": False,
         "user_data_dirs": []},
    ]
    _, page = _make_page(scan_data=scan_data, host_log_data=[],
                           hidden=[_norm(r"C:\Apps\A.exe")], monkeypatch=monkeypatch)
    table = _table(page)
    assert table.rowCount() == 1  # A 已隐藏

    # 找到「隐藏项」按钮并点击
    btn = next(b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "隐藏项")
    btn.click()
    _pump()

    dialogs = [w for w in QApplication.topLevelWidgets()
               if isinstance(w, QtWidgets.QDialog) and w.isVisible()
               and w.windowTitle() == "显示所有隐藏项"]
    assert dialogs, "「隐藏项」按钮未打开对话框"
    dlg = dialogs[0]
    assert dlg._list.count() == 1
    dlg.close()
    dlg.deleteLater()

    page.close()
    page.deleteLater()