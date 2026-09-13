"""托盘 MCP 命令分发回归测试：重命令不得阻塞主线程。

背景：MCP D5 缺陷——capture_module（grab）/ webview_kill（subprocess
timeout=5）/ export_logs（5000 行）/ scan_webview（refresh_list）在
主线程同步执行，会冻结 GUI。本文件验证这些重命令被路由到后台线程，
轻命令仍在主线程执行。
"""

import sys
sys.path.insert(0, ".")

import json
import os
import threading
import time

import pytest

from core.qt_bootstrap import import_qt

QtCore, QtGui, QtWidgets = import_qt()[1:]


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _make_tray():
    import core.tray.mcp as mcp_mod
    tray = object.__new__(mcp_mod.Tray)
    tray._context = None
    return tray


def _dispatch(tray, command, **extra):
    payload = {"command": command}
    payload.update(extra)
    tray._dispatch_mcp_command(payload)


def _wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_heavy_commands_run_in_worker_thread(monkeypatch):
    """重命令（capture/export/scan/kill）必须在非主线程执行。"""
    import core.tray.mcp as mcp_mod
    main_tid = threading.get_ident()
    captured = {}

    def recording_handler(self, *a, **k):
        captured["tid"] = threading.get_ident()

    monkeypatch.setattr(mcp_mod.Tray, "_mcp_capture_module", recording_handler)
    monkeypatch.setattr(mcp_mod.Tray, "_mcp_export_logs", recording_handler)
    monkeypatch.setattr(mcp_mod.Tray, "_mcp_scan_webview", recording_handler)
    monkeypatch.setattr(mcp_mod.Tray, "_mcp_webview_kill", recording_handler)

    tray = _make_tray()
    for cmd in ("capture_module", "export_logs", "scan_webview", "webview_kill"):
        captured.clear()
        _dispatch(tray, cmd)
        assert _wait_until(lambda: "tid" in captured), f"{cmd} 应已执行"
        assert captured["tid"] != main_tid, f"{cmd} 不得在主线程执行"


def test_light_commands_run_on_main_thread(monkeypatch):
    """轻命令（show_window 等）仍在主线程执行。"""
    import core.tray.mcp as mcp_mod
    main_tid = threading.get_ident()
    captured = {}

    def recording_handler(self, *a, **k):
        captured["tid"] = threading.get_ident()

    monkeypatch.setattr(mcp_mod.Tray, "_mcp_show_window", recording_handler)
    tray = _make_tray()
    _dispatch(tray, "show_window")
    assert captured["tid"] == main_tid


def test_capture_module_end_to_end_worker_grab(tmp_path):
    """capture_module 端到端：grab 在 worker 线程执行，reply 文件写出。"""
    import core.tray.mcp as mcp_mod
    _app()
    main_tid = threading.get_ident()
    grabbed_tid = {}

    class _FakeWidget:
        def isVisible(self):
            return True

        def grab(self):
            grabbed_tid["tid"] = threading.get_ident()
            pm = QtGui.QPixmap(10, 10)
            pm.fill(QtCore.Qt.GlobalColor.white)
            return pm

    class _FakeMod:
        id = "todo_notes"
        _widgets = [_FakeWidget()]

    class _FakeRegistry:
        def get(self, module_id):
            return _FakeMod()

    class _FakeContext:
        registry = _FakeRegistry()

    tray = _make_tray()
    tray._context = _FakeContext()
    reply_file = str(tmp_path / "reply.json")
    output_path = str(tmp_path / "shot.png")

    _dispatch(tray, "capture_module",
              module_id="todo_notes", output_path=output_path,
              reply_file=reply_file, widget_type=None)

    assert _wait_until(lambda: os.path.exists(reply_file)), "reply 文件应已写出"
    assert grabbed_tid["tid"] != main_tid, "grab() 不得在主线程执行"
    with open(reply_file, encoding="utf-8") as f:
        data = json.load(f)
    assert data["success"] is True
    assert data["result"] == output_path
    assert os.path.exists(output_path)