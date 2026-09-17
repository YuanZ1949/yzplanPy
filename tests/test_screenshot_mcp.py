"""MCP 截图工具客户区取景测试。

使用原生 Win32 窗口（STATIC 类）而非 Qt 窗口，避免与其它测试文件的
QApplication 平台（offscreen）冲突；win32 截图路径不依赖 Qt 窗口。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest
from PySide6.QtGui import QImage

import win32gui
import win32con

from mcp_server.tools_screenshot import (
    screenshot_window_by_title,
    _find_hwnd_by_title,
)

TITLE = "YZplanMCPTest_77"


@pytest.fixture
def native_window():
    hwnd = win32gui.CreateWindowEx(
        0,
        "STATIC",
        TITLE,
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE,
        100,
        100,
        640,
        480,
        0,
        0,
        win32gui.GetModuleHandle(None),
        None,
    )
    assert hwnd, "CreateWindowEx failed"
    win32gui.PumpWaitingMessages()
    time.sleep(0.2)
    yield hwnd
    try:
        win32gui.DestroyWindow(hwnd)
    except Exception:
        pass


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="requires interactive desktop session")
def test_find_hwnd_by_title(native_window):
    hwnd = _find_hwnd_by_title(TITLE)
    assert hwnd is not None
    assert TITLE in win32gui.GetWindowText(hwnd)


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="requires interactive desktop session")
def test_screenshot_window_by_title_returns_client_area(native_window, tmp_path):
    result = screenshot_window_by_title(TITLE, filename=str(tmp_path / "cap"))
    assert result["success"], result

    img = QImage(result["path"])
    cl = win32gui.GetClientRect(native_window)
    # 图像尺寸 == 窗口客户区尺寸（不含标题栏/边框）
    assert img.width() == cl[2]
    assert img.height() == cl[3]

    # 内容非全黑（像素熵检查）
    step_x = max(1, img.width() // 20)
    step_y = max(1, img.height() // 20)
    nonblack = 0
    total = 0
    for x in range(0, img.width(), step_x):
        for y in range(0, img.height(), step_y):
            total += 1
            c = img.pixelColor(x, y)
            if c.red() + c.green() + c.blue() > 60:
                nonblack += 1
    assert total > 0
    assert nonblack / total > 0.5


def test_screenshot_window_by_title_missing():
    result = screenshot_window_by_title("YZplanNoSuchWindow_zzz_999")
    assert not result["success"]
    assert "未找到" in result["message"]


def test_mcp_inbox_command_reply_goes_to_outbox(tmp_path, monkeypatch):
    """回归：reply 文件必须写 mcp_outbox 而非 mcp_inbox。

    GUI 托盘 _poll 会扫描并删除 inbox 下所有 *.json（含 reply 文件），
    导致 MCP 读 reply 时 FileNotFoundError（异常被吞）→ 10s 假超时，
    即使截图已成功。tools_perf.py 已正确写 outbox（GUI 不扫 outbox）。
    """
    import json
    import threading

    from mcp_server import tools_screenshot as ts

    monkeypatch.setattr("core.constants.DATA_DIR", str(tmp_path))
    inbox = tmp_path / "mcp_inbox"
    outbox = tmp_path / "mcp_outbox"

    payload = {
        "id": "test_reply_outbox_001",
        "module_id": "rss_aggregator",
        "title": "截图",
        "message": "测试",
        "silent": True,
    }

    result_holder = {}

    def _run():
        result_holder["result"] = ts._mcp_inbox_command("capture_module", payload)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    cmd_file = inbox / f"{payload['id']}.json"
    deadline = time.time() + 5
    while not cmd_file.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert cmd_file.exists(), "命令文件应写入 inbox"

    cmd = json.loads(cmd_file.read_text(encoding="utf-8"))
    reply_file = cmd["reply_file"]

    # 关键断言：reply 必须写 outbox（GUI 不扫 outbox），而非 inbox（GUI 会删）
    assert os.path.dirname(reply_file) == str(outbox), (
        f"reply 文件必须写入 mcp_outbox，实际写入: {reply_file}"
    )

    # 写入回复让等待循环返回
    with open(reply_file, "w", encoding="utf-8") as f:
        json.dump({"success": True, "result": "ok"}, f, ensure_ascii=False)

    t.join(timeout=5)
    assert not t.is_alive(), "收到回复后 _mcp_inbox_command 应返回"
    assert result_holder["result"].get("success") is True