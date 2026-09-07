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


def test_find_hwnd_by_title(native_window):
    hwnd = _find_hwnd_by_title(TITLE)
    assert hwnd is not None
    assert TITLE in win32gui.GetWindowText(hwnd)


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