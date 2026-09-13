"""win_maintenance 模块测试：store 数据层 + home/page 构建 + 子进程冒烟。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

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

def test_aggregate_errors_groups_by_source_and_event_id(monkeypatch):
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
    # 4 条 → 3 个 (source, event_id) 组（brief 中"2 组"为笔误）
    assert len(groups) == 3
    # 按 count 降序：count=2 的组排第一
    assert groups[0]["source"] == "Kernel-Power"
    assert groups[0]["event_id"] == 41
    assert groups[0]["count"] == 2
    assert groups[0]["first_time"] == "2026-09-13 10:00:00"
    assert groups[0]["last_time"] == "2026-09-13 10:05:30"
    assert groups[0]["duration_s"] == 330  # 10:05:30 - 10:00:00
    assert groups[0]["message"] == "系统重启(新)"  # 组内最新一条
    # 其余两组 count=1、duration=0
    rest = groups[1:]
    assert sorted((g["source"], g["event_id"]) for g in rest) == [
        ("Kernel-Power", 42),
        ("Service Control Manager", 7000),
    ]
    for g in rest:
        assert g["count"] == 1
        assert g["duration_s"] == 0
        assert g["first_time"] == g["last_time"]


def test_aggregate_errors_empty_input_returns_empty(monkeypatch):
    monkeypatch.setattr(wm_store, "read_event_log", lambda *a, **k: [])
    assert wm_store.aggregate_errors() == []


def test_aggregate_errors_forwards_filters_to_read_event_log(monkeypatch):
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
    return w


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


def test_page_csv_export_cancel_no_crash():
    w = _make_page()
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    w._export_csv()  # 不应抛异常
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
    t = w.findChild(QtWidgets.QTableWidget)
    assert t is not None

    # 过滤：24h + 仅错误/警告
    range_cb = [c for c in w.findChildren(ComboBox) if c.itemText(0) == "最近1小时"][0]
    range_cb.setCurrentIndex(1)
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    info_cb = [c for c in w.findChildren(QtWidgets.QCheckBox) if c.text() == "信息"][0]
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
    w._export_csv()
    with open(out, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"

    # 关闭
    w.close()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    print("WIN_MAINTENANCE_SMOKE_OK")