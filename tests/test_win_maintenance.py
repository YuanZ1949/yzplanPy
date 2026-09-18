"""win_maintenance 模块测试：store 数据层 + home/page 构建 + 子进程冒烟。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.win_maintenance import store as wm_store
from modules.win_maintenance import (
    read_event_log,
    get_log_stats,
    LEVEL_ERROR,
    LEVEL_WARNING,
)

win32evtlog = pytest.importorskip("win32evtlog")


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


class _Owner:
    pass


# ── store：真实事件日志 ────────────────────────────────────────────

def test_read_event_log_returns_list_of_dicts():
    rows = read_event_log("System", limit=5)
    assert isinstance(rows, list)
    for r in rows:
        assert isinstance(r, dict)
        for key in ("time", "source", "level", "event_id", "message"):
            assert key in r, f"缺少字段 {key}"


def test_read_event_log_level_filter():
    rows = read_event_log("System", level=LEVEL_ERROR, limit=20)
    for r in rows:
        assert r["level"] == "错误"


def test_read_event_log_level_list_filter():
    rows = read_event_log("System", level=[LEVEL_ERROR, LEVEL_WARNING], limit=20)
    for r in rows:
        assert r["level"] in ("错误", "警告")


def test_read_event_log_keyword_filter():
    rows = read_event_log("System", keyword="kernel", limit=20)
    for r in rows:
        blob = (r["source"] + " " + r["message"]).lower()
        assert "kernel" in blob


def test_read_event_log_date_from_filter():
    import datetime
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=1)
    rows = read_event_log("System", date_from=cutoff, limit=20)
    for r in rows:
        ts = datetime.datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
        assert ts >= cutoff


def test_get_log_stats_returns_counts():
    stats = get_log_stats("System")
    assert isinstance(stats, dict)
    for name in ("错误", "警告", "信息", "成功", "失败"):
        assert name in stats
        assert isinstance(stats[name], int)
        assert stats[name] >= 0


# ── store：失败路径（日志不可用）──────────────────────────────────

def test_read_event_log_invalid_type_returns_empty():
    assert read_event_log("NoSuchLog") == []


def test_read_event_log_import_missing_returns_empty(monkeypatch):
    monkeypatch.setattr(wm_store, "_import_evtlog", lambda: None)
    assert read_event_log("System") == []


def test_read_event_log_open_failure_returns_empty(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("access denied")
    monkeypatch.setattr(win32evtlog, "OpenEventLog", _boom)
    assert read_event_log("System") == []


def test_get_log_stats_import_missing_returns_zeros(monkeypatch):
    monkeypatch.setattr(wm_store, "_import_evtlog", lambda: None)
    stats = get_log_stats("System")
    assert all(v == 0 for v in stats.values())


# ── store：aggregate_errors 聚合 ─────────────────────────────────

def test_aggregate_errors_groups_by_source_event_id_and_fingerprint(monkeypatch):
    """不同消息 → 不同分组；相同 source+event_id 但消息不同产生独立组。"""
    rows = [
        {"time": "2026-09-13 10:00:00", "source": "Kernel-Power",
         "level": "错误", "event_id": 41, "message": "系统重启"},
        {"time": "2026-09-13 10:05:30", "source": "Kernel-Power",
         "level": "错误", "event_id": 41, "message": "系统重启(新)"},
        {"time": "2026-09-13 11:00:00", "source": "Service Control Manager",
         "level": "错误", "event_id": 7000, "message": "服务启动失败"},
        {"time": "2026-09-13 12:00:00", "source": "Kernel-Power",
         "level": "错误", "event_id": 42, "message": "其他事件"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    # 4 条 → 4 个 (source, event_id, fingerprint) 组
    # 因为两条 Kernel-Power 41 的消息不同 → 2 个独立组
    assert len(groups) == 4
    # 按 count 降序：count=1 的组全部并列
    for g in groups:
        assert g["count"] == 1
        assert g["duration_s"] == 0
        assert g["first_time"] == g["last_time"]
        assert "fingerprint" in g
    # 两条 Kernel-Power 41 消息不同的组各自独立
    kp41 = [g for g in groups if g["source"] == "Kernel-Power" and g["event_id"] == 41]
    assert len(kp41) == 2
    assert {g["message"] for g in kp41} == {"系统重启", "系统重启(新)"}


def test_aggregate_errors_same_source_event_id_different_messages_two_groups(
    monkeypatch,
):
    """同 source+event_id，两条消息完全不同 → 2 个聚合组。"""
    rows = [
        {"time": "2026-09-14 08:00:00", "source": "S", "level": "错误",
         "event_id": 100, "message": "Alpha failure"},
        {"time": "2026-09-14 09:00:00", "source": "S", "level": "错误",
         "event_id": 100, "message": "Beta failure"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    assert len(groups) == 2
    assert groups[0]["count"] == 1
    assert groups[1]["count"] == 1
    assert groups[0]["fingerprint"] != groups[1]["fingerprint"]
    assert {g["message"] for g in groups} == {"Alpha failure", "Beta failure"}


def test_aggregate_errors_whitespace_only_difference_same_group(monkeypatch):
    """消息仅在前导/尾随/连续空格上不同 → 同一指纹 → 1 个聚合组。"""
    rows = [
        {"time": "2026-09-14 08:00:00", "source": "S", "level": "错误",
         "event_id": 200, "message": "  disk  error  "},
        {"time": "2026-09-14 09:00:00", "source": "S", "level": "错误",
         "event_id": 200, "message": "disk error"},
        {"time": "2026-09-14 10:00:00", "source": "S", "level": "错误",
         "event_id": 200, "message": "disk   error"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    assert len(groups) == 1
    g = groups[0]
    assert g["count"] == 3
    assert g["source"] == "S"
    assert g["event_id"] == 200
    # 首次=最早，最近=最晚
    assert g["first_time"] == "2026-09-14 08:00:00"
    assert g["last_time"] == "2026-09-14 10:00:00"
    assert g["duration_s"] == 7200  # 2 hours


def test_aggregate_errors_fingerprint_count_matches_members(monkeypatch):
    """每组 count 精确等于属于该指纹的成员条数。"""
    rows = [
        {"time": "2026-09-14 08:00:00", "source": "A", "level": "错误",
         "event_id": 1, "message": "X"},
        {"time": "2026-09-14 08:01:00", "source": "A", "level": "错误",
         "event_id": 1, "message": "X"},
        {"time": "2026-09-14 08:02:00", "source": "A", "level": "错误",
         "event_id": 1, "message": "X"},
        {"time": "2026-09-14 08:03:00", "source": "A", "level": "错误",
         "event_id": 1, "message": "Y"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    assert len(groups) == 2
    g_x = next(g for g in groups if g["message"] == "X")
    g_y = next(g for g in groups if g["message"] == "Y")
    assert g_x["count"] == 3
    assert g_y["count"] == 1


def test_aggregate_errors_first_time_le_last_time_and_duration(monkeypatch):
    """first_time ≤ last_time，duration_s 与时间差一致。"""
    rows = [
        {"time": "2026-09-14 08:00:00", "source": "S", "level": "警告",
         "event_id": 50, "message": "slow query"},
        {"time": "2026-09-14 08:05:00", "source": "S", "level": "警告",
         "event_id": 50, "message": "slow query"},
        {"time": "2026-09-14 08:15:30", "source": "S", "level": "警告",
         "event_id": 50, "message": "slow query"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    assert len(groups) == 1
    g = groups[0]
    assert g["first_time"] <= g["last_time"]
    assert g["count"] == 3
    assert g["duration_s"] == 930  # 15 min 30 sec


def test_aggregate_errors_all_records_have_fingerprint(monkeypatch):
    """每条聚合记录都包含 fingerprint 字段（字符串）。"""
    rows = [
        {"time": "2026-09-14 08:00:00", "source": "X", "level": "信息",
         "event_id": 10, "message": "hello"},
    ]
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: rows)
    groups = wm_store.aggregate_errors()
    assert len(groups) == 1
    fp = groups[0]["fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) > 0
    captured = {}

    def _fake(*a, **k):
        captured["args"] = (a, k)
        return []

    monkeypatch.setattr(wm_store, "read_event_log", _fake)
    wm_store.aggregate_errors(
        log_type="Application", level=LEVEL_ERROR, keyword="disk",
        date_from="2026-09-01", limit=50)
    args, kwargs = captured["args"]
    assert args == ("Application",)
    assert kwargs == {"level": LEVEL_ERROR, "keyword": "disk",
                      "date_from": "2026-09-01", "limit": 50}


# ── home：构建与统计显示 ──────────────────────────────────────────

def test_home_widget_builds_and_shows_counts():
    _app()
    from modules.win_maintenance.home import _make_home_widget
    w = _make_home_widget(_Owner(), None)
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    texts = [c.text() for c in w.findChildren(QtWidgets.QLabel)]
    assert "Windows维护" in texts
    assert "系统日志" in texts
    assert "应用日志" in texts
    # 计数标签为数字（日志不可用时为 0）
    digits = [t for t in texts if t.isdigit()]
    assert len(digits) >= 6
    w.close()


def test_home_widget_has_30s_timer():
    _app()
    from modules.win_maintenance.home import _make_home_widget, _REFRESH_MS
    w = _make_home_widget(_Owner(), None)
    timer = w.findChild(QtCore.QTimer)
    assert timer is not None
    assert timer.interval() == _REFRESH_MS
    assert timer.isActive()
    w.close()


# ── page：构建 / 过滤 / 颜色 / 导出 ───────────────────────────────

def _make_page():
    _app()
    from modules.win_maintenance.page import _make_page_widget
    w = _make_page_widget(_Owner(), None)
    w.resize(1000, 700)
    w.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    # 页面现为 2-tab 容器（日志列表 + 聚合时间线），既有用例锁定 _LogPage tab；
    # _page_ref 保持页面存活（否则局部 w 被 GC 后 C++ 对象被销毁）
    tabs = w.findChild(QtWidgets.QTabWidget)
    lp = tabs.widget(0)
    lp._page_ref = w
    return lp


def _table(w):
    return w.findChild(QtWidgets.QTableWidget)


def _combos(w):
    from qfluentwidgets import ComboBox
    return w.findChildren(ComboBox)


def test_page_builds_with_table_and_columns():
    w = _make_page()
    t = _table(w)
    assert t is not None
    assert t.columnCount() == 5
    headers = [t.horizontalHeaderItem(i).text() for i in range(5)]
    assert headers == ["时间", "来源", "级别", "事件ID", "消息摘要"]
    # 列宽：150/140/60/70/消息摘要 stretch
    assert t.columnWidth(0) == 150
    assert t.columnWidth(1) == 140
    assert t.columnWidth(2) == 60
    assert t.columnWidth(3) == 70
    assert t.horizontalHeader().sectionResizeMode(4) == QtWidgets.QHeaderView.Stretch
    # 只读
    assert t.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers
    w.close()


def test_page_has_filter_controls():
    w = _make_page()
    combos = _combos(w)
    assert len(combos) == 2
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == \
        ["System", "Application", "Security"]
    assert [combos[1].itemText(i) for i in range(combos[1].count())] == \
        ["最近1小时", "最近24小时", "最近7天", "最近30天"]
    checks = [c.text() for c in w.findChildren(QtWidgets.QCheckBox)]
    assert checks == ["错误", "警告", "信息"]
    assert w.findChild(QtWidgets.QLineEdit) is not None
    buttons = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert "刷新" in buttons
    assert "导出 CSV" in buttons
    assert "上一页" in buttons
    assert "下一页" in buttons
    w.close()


def test_page_level_filter_and_row_colors():
    w = _make_page()
    t = _table(w)
    # 放宽到 24h 保证有错误/警告行
    range_cb = [c for c in _combos(w) if c.itemText(0) == "最近1小时"][0]
    range_cb.setCurrentIndex(1)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    info_cb = [c for c in w.findChildren(QtWidgets.QCheckBox) if c.text() == "信息"][0]
    info_cb.setChecked(False)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    assert t.rowCount() > 0
    for r in range(t.rowCount()):
        level = t.item(r, 2).text()
        assert level in ("错误", "警告")
        fg = t.item(r, 0).foreground().color().name()
        if level == "错误":
            assert fg == "#d93025"
        else:
            assert fg == "#e8710a"
    w.close()


def test_page_pagination():
    w = _make_page()
    t = _table(w)
    range_cb = [c for c in _combos(w) if c.itemText(0) == "最近1小时"][0]
    range_cb.setCurrentIndex(1)  # 24h
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    if t.rowCount() < 50:
        w.close()
        return  # 日志不足一页，跳过分页断言
    label = [c for c in w.findChildren(QtWidgets.QLabel) if "页" in c.text()][0]
    assert "第 1/" in label.text()
    next_btn = [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "下一页"][0]
    assert next_btn.isEnabled()
    next_btn.click()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert "第 2/" in label.text()
    w.close()


def test_page_csv_export_utf8_sig(tmp_path):
    w = _make_page()
    range_cb = [c for c in _combos(w) if c.itemText(0) == "最近1小时"][0]
    range_cb.setCurrentIndex(1)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    out = tmp_path / "export.csv"
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (str(out), "CSV 文件 (*.csv)"))
    w._export_csv()
    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "CSV 应带 utf-8-sig BOM"
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0] == "时间,来源,级别,事件ID,消息"
    assert len(lines) >= 2
    w.close()


# ── 子进程冒烟：打开→过滤→颜色→导出→关闭 ─────────────────────────

def test_page_smoke_no_crash_subprocess():
    """Subprocess isolation: open page → filter → row colors → CSV export → close."""
    import subprocess
    from pathlib import Path
    child_name = "test_page_smoke_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_win_maintenance.py::{child_name}",
         "-q"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )


def test_page_smoke_no_crash_child():
    """Child: full page flow — build, filter, colors, CSV export, close."""
    import tempfile
    from modules.win_maintenance.page import _make_page_widget
    from qfluentwidgets import ComboBox

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    w = _make_page_widget(_Owner(), None)
    w.resize(1000, 700)
    w.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    tabs = w.findChild(QtWidgets.QTabWidget)
    lp = tabs.widget(0)  # _LogPage tab
    t = lp.findChild(QtWidgets.QTableWidget)
    assert t is not None

    # 过滤：24h + 仅错误/警告
    range_cb = [c for c in lp.findChildren(ComboBox) if c.itemText(0) == "最近1小时"][0]
    range_cb.setCurrentIndex(1)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    info_cb = [c for c in lp.findChildren(QtWidgets.QCheckBox) if c.text() == "信息"][0]
    info_cb.setChecked(False)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    for r in range(t.rowCount()):
        level = t.item(r, 2).text()
        assert level in ("错误", "警告")
        fg = t.item(r, 0).foreground().color().name()
        assert fg in ("#d93025", "#e8710a")

    # CSV 导出
    out = os.path.join(tempfile.mkdtemp(), "smoke.csv")
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (out, "CSV 文件 (*.csv)"))
    lp._export_csv()
    with open(out, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"

    # 关闭
    w.close()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    print("WIN_MAINTENANCE_SMOKE_OK")


# ── 聚合时间线视图：假 store 单元 + 子进程冒烟 ───────────────────────

class _FakeStore:
    """固定 2 组聚合结果（A: count=15 时长 1800s；B: count=3 时长 0）。"""

    def aggregate_errors(self, log_type, level, keyword=None, date_from=None):
        return [
            {"source": "SvcHost", "event_id": 1001, "count": 15,
             "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 08:30:00",
             "duration_s": 1800, "message": "服务崩溃 A"},
            {"source": "Kernel-Power", "event_id": 41, "count": 3,
             "first_time": "2026-09-13 09:00:00", "last_time": "2026-09-13 09:00:00",
             "duration_s": 0, "message": "系统重启 B"},
        ]


def test_agg_view_populates_rows_from_fake_store():
    _app()
    from modules.win_maintenance.agg_view import _AggregationView, _fmt_duration
    from core.theme.tokens import theme_palette
    v = _AggregationView(_FakeStore())
    v.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    t = v.findChild(QtWidgets.QTableWidget)
    assert t is not None
    assert t.rowCount() == 2
    assert t.item(0, 2).text() == "15"
    assert t.item(1, 2).text() == "3"
    assert t.item(0, 5).text() == _fmt_duration(1800)
    assert t.item(0, 2).foreground().color() == \
        QtGui.QColor(theme_palette()["status_error"])
    labels = [c.text() for c in v.findChildren(QtWidgets.QLabel)]
    assert "共 2 组 · 覆盖事件 18 次" in labels
    v.close()


def test_agg_view_smoke_no_crash_subprocess():
    """Subprocess isolation: maintenance page → aggregation tab → empty state → close."""
    import subprocess
    from pathlib import Path
    child_name = "test_agg_view_smoke_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_win_maintenance.py::{child_name}",
         "-q", "-s"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )
    assert "AGG_VIEW_OK" in result.stdout.decode(errors="replace")


def test_agg_view_smoke_no_crash_child():
    """Child: maintenance page → 2 tabs → aggregation empty state → dbl-click → close."""
    from modules.win_maintenance import store as wm_store
    from modules.win_maintenance.page import _make_page_widget

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    # 空态确定性：真实事件日志可能含错误组，patch 为固定空结果
    wm_store.aggregate_errors = lambda *a, **k: []

    page = _make_page_widget(None, None)
    page.resize(1000, 700)
    page.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()

    tabs = page.findChild(QtWidgets.QTabWidget)
    assert tabs is not None
    assert tabs.count() == 3
    assert tabs.tabText(1) == "聚合时间线"
    assert tabs.tabText(2) == "错误时间线"

    tabs.setCurrentIndex(1)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()

    labels = [c.text() for c in page.findChildren(QtWidgets.QLabel)]
    assert any("共 0 组" in t for t in labels), labels

    agg_tables = [t for t in page.findChildren(QtWidgets.QTableWidget)
                  if t.columnCount() == 7]
    assert agg_tables, "应存在 7 列聚合表"
    agg_tables[0].cellDoubleClicked.emit(0, 0)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()

    page.close()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    print("AGG_VIEW_OK")


# ── 甘特式错误时间线图：timeline widget ───────────────────────────

class _FakeStoreTimeline:
    """固定 3 组聚合结果（含 level/fingerprint），供时间线测试。"""

    def aggregate_errors(self, log_type="System", level=None, keyword=None,
                         date_from=None, limit=200):
        return [
            {"source": "SvcHost", "event_id": 1001, "count": 15,
             "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 08:30:00",
             "duration_s": 1800, "message": "服务崩溃", "level": "错误",
             "fingerprint": "abc123"},
            {"source": "Kernel-Power", "event_id": 41, "count": 3,
             "first_time": "2026-09-13 09:00:00", "last_time": "2026-09-13 09:00:00",
             "duration_s": 0, "message": "系统重启", "level": "警告",
             "fingerprint": "def456"},
            {"source": "Disk", "event_id": 11, "count": 8,
             "first_time": "2026-09-13 10:00:00", "last_time": "2026-09-13 12:00:00",
             "duration_s": 7200, "message": "磁盘错误", "level": "错误",
             "fingerprint": "ghi789"},
        ]


def test_maintenance_page_has_3_tabs():
    """_MaintenancePage 应有 3 个页签：日志列表 / 聚合时间线 / 错误时间线。"""
    _app()
    from modules.win_maintenance.agg_view import _MaintenancePage
    page = _MaintenancePage(None)
    tabs = page.findChild(QtWidgets.QTabWidget)
    assert tabs is not None
    assert tabs.count() == 3
    texts = [tabs.tabText(i) for i in range(3)]
    assert "日志列表" in texts
    assert "聚合时间线" in texts
    assert "错误时间线" in texts
    page.close()


def test_timeline_widget_instantiable():
    """_ErrorTimeline 可离屏实例化且不崩溃。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert w is not None
    w.close()


def test_timeline_paint_empty():
    """空数据 paintEvent 不抛异常。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    w.set_groups([])
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    w.close()


def test_timeline_paint_single_group():
    """单组数据 paintEvent 正常，bar_rects 长度 1。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    w.set_groups([_FakeStoreTimeline().aggregate_errors()[0]])
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert len(w.bar_rects) == 1
    w.close()


def test_timeline_paint_multi_group():
    """多组数据 paintEvent 正常，bar_rects 长度 3。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    store = _FakeStoreTimeline()
    w = _ErrorTimeline(store)
    w.resize(600, 400)
    w.show()
    w.set_groups(store.aggregate_errors())
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert len(w.bar_rects) == 3
    w.close()


def test_timeline_bar_length_monotonic():
    """条形像素宽度与 duration_s 单调相关（0 < 短 < 长）。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(800, 300)
    w.show()
    zero = {"source": "A", "event_id": 1, "count": 1,
            "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 08:00:00",
            "duration_s": 0, "message": "zero", "level": "警告", "fingerprint": "z"}
    short = {"source": "B", "event_id": 2, "count": 1,
             "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 08:10:00",
             "duration_s": 600, "message": "short", "level": "错误", "fingerprint": "s"}
    long_ = {"source": "C", "event_id": 3, "count": 1,
             "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 12:00:00",
             "duration_s": 14400, "message": "long", "level": "错误", "fingerprint": "l"}
    w.set_groups([zero, short, long_])
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    rects = w.bar_rects
    assert len(rects) == 3
    widths = [r.width() for _, r in rects]
    assert widths[0] <= widths[1] <= widths[2], f"宽度应单调: {widths}"
    assert widths[0] <= 6, "零时长条形应为最小宽度"
    w.close()


def test_timeline_colors_from_palette():
    """级别颜色映射必须引用 theme_palette 中存在的令牌 key。"""
    from modules.win_maintenance.timeline import _LEVEL_COLOR_KEY
    from core.theme.tokens import theme_palette
    p = theme_palette()
    for level, key in _LEVEL_COLOR_KEY.items():
        assert key in p, f"令牌 '{key}'（级别 {level}）不在 theme_palette 中"


def test_timeline_no_hardcoded_colors():
    """timeline.py 不得包含 QColor('hex') 硬编码颜色字面量。"""
    from pathlib import Path
    import re
    src = Path("modules/win_maintenance/timeline.py").read_text(encoding="utf-8")
    qcolor_hex = re.findall(r'QColor\(["\']#[0-9a-fA-F]{3,8}', src)
    assert not qcolor_hex, f"发现硬编码 hex 颜色: {qcolor_hex}"


def test_timeline_time_range_switch():
    """切换时间范围（1h/24h/7d）触发带不同 date_from 的刷新。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    calls = []

    def fake_aggregate(**kwargs):
        calls.append(kwargs)
        return [
            {"source": "A", "event_id": 1, "count": 5,
             "first_time": "2026-09-13 08:00:00", "last_time": "2026-09-13 08:10:00",
             "duration_s": 600, "message": "test", "level": "错误", "fingerprint": "a"},
        ]

    class _Store:
        aggregate_errors = staticmethod(fake_aggregate)

    w = _ErrorTimeline(_Store())
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()

    initial = len(calls)
    assert initial >= 1, "初始化应触发一次刷新"

    w._range_buttons["1h"].click()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert len(calls) > initial, "切到 1h 应触发刷新"

    w._range_buttons["7d"].click()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert len(calls) > initial + 1, "切到 7d 应触发刷新"

    w.close()


# ── 时间线可读性（Todo 14）：不透明画布 / elide / 整行 tooltip / 失败路径 ──

def test_timeline_canvas_opaque_background():
    """paintEvent 后画布背景像素 alpha==255 且颜色 == wp_timeline_bg 令牌。

    用 render(flags=0)（不画默认窗口背景）渲染：只有 paintEvent 自己画的内容
    会落盘——fillRect 缺失时采样点保持透明（alpha 0），修复后为 255；颜色断言
    锁定「背景主色」必须等于令牌（防止回归成其他底色/半透明叠加）。
    采样点取纯背景区（左上角顶部刻度区 + 左下角底部留白）；中心点可能落在
    半透明轨道/条形上，只断言 alpha 不透明。
    """
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    from core.theme.tokens import theme_palette
    try:
        for dark in (True, False):
            _force_dark(dark)
            expected = QtGui.QColor(theme_palette()["wp_timeline_bg"])
            w = _ErrorTimeline(_FakeStoreTimeline())
            w.resize(600, 300)
            w.show()
            w.set_groups(_FakeStoreTimeline().aggregate_errors())
            for _ in range(5):
                QtWidgets.QApplication.processEvents()
            chart = w._chart
            img = QtGui.QImage(chart.width(), chart.height(),
                               QtGui.QImage.Format_ARGB32_Premultiplied)
            img.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(img)
            chart.render(p, QtCore.QPoint(), QtGui.QRegion(),
                         QtWidgets.QWidget.RenderFlags(0))
            p.end()
            for x, y in ((2, 2), (2, chart.height() - 2)):
                c = img.pixelColor(x, y)
                assert c.alpha() == 255, \
                    f"dark={dark} 像素({x},{y}) alpha={c.alpha()} 应不透明"
                assert c == expected, \
                    f"dark={dark} 像素({x},{y}) 颜色 {c.name()} 应等于 " \
                    f"wp_timeline_bg {expected.name()}"
            c = img.pixelColor(chart.width() // 2, chart.height() // 2)
            assert c.alpha() == 255, \
                f"dark={dark} 中心像素 alpha={c.alpha()} 应不透明"
            w.close()
    finally:
        _restore_dark()


def test_timeline_labels_use_elided_text(monkeypatch):
    """标签绘制走 QFontMetrics.elidedText（每行标签一次，长文本省略号）。"""
    _app()
    from modules.win_maintenance import timeline as tl
    from modules.win_maintenance import timeline_chart as tlc
    calls = []
    real = tlc._elide_label

    def spy(fm, text, width):
        calls.append(text)
        return real(fm, text, width)

    monkeypatch.setattr(tlc, "_elide_label", spy)
    w = tl._ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    w.set_groups(_FakeStoreTimeline().aggregate_errors())
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    assert len(calls) >= 6, f"3 组 × 2 行标签都应走 elide，实际 {len(calls)} 次"
    w.close()


def test_timeline_elide_label_truncates_long_text():
    """超长文本被省略号截断，短文本原样返回。"""
    _app()
    from modules.win_maintenance.timeline import _elide_label
    fm = QtGui.QFontMetrics(QtGui.QFont())
    long_text = "x" * 500
    out = _elide_label(fm, long_text, 80)
    assert len(out) < len(long_text)
    assert out.endswith("…")
    assert _elide_label(fm, "短", 80) == "短"


def test_timeline_tooltip_whole_row_and_full_message(monkeypatch):
    """悬浮整行（非仅条形）弹出含完整 message 的 tooltip。"""
    _app()
    from modules.win_maintenance import timeline_chart as tlc
    from modules.win_maintenance.timeline import _ErrorTimeline
    shown = []
    monkeypatch.setattr(
        tlc, "_show_tooltip", lambda widget, pos, text: shown.append(text))
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    groups = _FakeStoreTimeline().aggregate_errors()
    w.set_groups(groups)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    chart = w._chart
    row = chart.row_rects[0][1]
    # 命中标签列（x=10，条形起点在 label_w+8 之后）→ 整行命中而非仅条形
    pos = QtCore.QPointF(10, row.center().y())
    ev = QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove, pos, chart.mapToGlobal(pos.toPoint()),
        QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
    chart.mouseMoveEvent(ev)
    assert len(shown) == 1, f"应弹出 1 次 tooltip，实际 {len(shown)}"
    assert f"{groups[0]['source']} [{groups[0]['event_id']}]" in shown[0]
    assert groups[0]["message"] in shown[0], "tooltip 应含完整 message"
    w.close()


def test_timeline_paint_failure_paths_message_variants():
    """message 为空/超长/含换行 时 paintEvent 不崩且仍绘制。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    base = _FakeStoreTimeline().aggregate_errors()[0]
    variants = [
        {**base, "message": ""},
        {**base, "message": "x" * 5000},
        {**base, "message": "第一行\n第二行\n第三行"},
    ]
    for v in variants:
        w = _ErrorTimeline(_FakeStoreTimeline())
        w.resize(600, 300)
        w.show()
        w.set_groups([v])
        for _ in range(5):
            QtWidgets.QApplication.processEvents()
        assert len(w.bar_rects) == 1, f"message={v['message'][:20]!r} 仍应绘制"
        w.close()


# ── 时间线可滚动（Todo 15）：QScrollArea + 高度随组数增长 ──

def test_timeline_scrollable_many_groups():
    """20 组数据：图表最小高度随组数增长，滚动条出现且不丢行。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    base = _FakeStoreTimeline().aggregate_errors()[0]
    groups = [{**base, "event_id": i, "source": f"S{i}"} for i in range(20)]
    w.set_groups(groups)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    chart = w._chart
    # 无丢行：全部 20 行都绘制（paintEvent 的 break 守卫不应触发）
    assert len(w.bar_rects) == 20, f"应绘制 20 行，实际 {len(w.bar_rects)}"
    # 最小高度随组数增长：22 + 20*row_h + 6 应超过视口高度
    assert chart.minimumHeight() > w._scroll.viewport().height(), \
        "20 组时图表最小高度应超过视口高度（出现滚动条）"
    sb = w._scroll.verticalScrollBar()
    assert sb.maximum() > 0, "20 组时应出现垂直滚动条"
    # 滚动到底部能看到最后一行
    sb.setValue(sb.maximum())
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    last = chart.row_rects[-1][1]
    visible_top = sb.value()
    visible_bottom = sb.value() + w._scroll.viewport().height()
    assert last.top() < visible_bottom and last.bottom() > visible_top, \
        "滚动到底后最后一行应在可视区域内"
    w.close()


def test_timeline_empty_no_scrollbar():
    """0 组数据：空状态显示，不出现滚动条。"""
    _app()
    from modules.win_maintenance.timeline import _ErrorTimeline
    w = _ErrorTimeline(_FakeStoreTimeline())
    w.resize(600, 300)
    w.show()
    w.set_groups([])
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    sb = w._scroll.verticalScrollBar()
    assert sb.maximum() == 0, "0 组时不应出现滚动条"
    w.close()