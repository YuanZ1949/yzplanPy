"""截图模块 Win32 捕获 GDI 缺陷回归测试（2.1 / 2.2 / 2.3）。

用假 win32gui / win32ui 模块替换 screenshot_core 命名空间中的真实模块，
在无真实窗口的 CI 环境模拟 GDI 调用序列，锁定三个已确认缺陷：
- 2.1 异常路径也必须 ReleaseDC / DeleteDC / DeleteObject（GDI 泄漏）
- 2.2 DeleteObject 前必须先解除位图选中（还原旧对象）
- 2.3 GetBitmapBits(True) 的 bottom-up 扫描行必须经 mirrored() 修正
"""
import os
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# 冷进程直接 import PySide6 会触发 Qt6Core 的 icuuc.dll 解析 bug
# （WinError 127 / 0xc0000139），必须先经 qt_bootstrap 预载 ICU DLL。
from core.qt_bootstrap import import_qt

_, _, QtGui, _ = import_qt()
QImage = QtGui.QImage

from modules.screenshot.screenshot_core import ScreenshotCore


# ── 假 Win32 GDI 对象：记录调用序列并模拟选中/释放语义 ─────────────────

class _FakeBitmap:
    _next_handle = 1000

    def __init__(self, ui):
        self.ui = ui
        self.handle = _FakeBitmap._next_handle
        _FakeBitmap._next_handle += 1
        self.width = 0
        self.height = 0
        self.bits = b""

    def CreateCompatibleBitmap(self, dc, width, height):
        self.width = width
        self.height = height
        self.ui.events.append("CreateCompatibleBitmap")

    def GetInfo(self):
        return {"bmWidth": self.width, "bmHeight": self.height}

    def GetBitmapBits(self, bottom_up=True):
        self.ui.events.append(f"GetBitmapBits({bottom_up})")
        return self.bits

    def GetHandle(self):
        return self.handle


class _FakeDC:
    def __init__(self, ui, name):
        self.ui = ui
        self.name = name
        self.current = None  # 当前选中的 GDI 对象

    def CreateCompatibleDC(self):
        self.ui.events.append("CreateCompatibleDC")
        dc = _FakeDC(self.ui, "save")
        self.ui.dcs.append(dc)
        return dc

    def SelectObject(self, obj):
        old = self.current
        self.current = obj
        self.ui.events.append(
            f"SelectObject({obj.handle if obj is not None else 'old'})")
        return old

    def BitBlt(self, *args):
        self.ui.events.append("BitBlt")
        gui = self.ui.gui
        if gui is not None and gui.bitblt_raises:
            raise RuntimeError("BitBlt failed")

    def DeleteDC(self):
        self.ui.events.append(f"DeleteDC({self.name})")


class _FakeWin32Ui:
    def __init__(self, gui: Optional["_FakeWin32Gui"] = None):
        self.gui = gui
        self.events = []
        self.dcs = []
        self.next_bits = b""

    def CreateDCFromHandle(self, hwnd_dc):
        self.events.append("CreateDCFromHandle")
        dc = _FakeDC(self, "mfc")
        self.dcs.append(dc)
        return dc

    def CreateBitmap(self):
        self.events.append("CreateBitmap")
        bmp = _FakeBitmap(self)
        bmp.bits = self.next_bits
        return bmp


class _FakeWin32Gui:
    def __init__(self, ui):
        self.ui = ui
        self.events = ui.events
        self.rect = (0, 0, 100, 80)
        self.window_text = "TestWindow"
        self.release_calls = []
        self.delete_while_selected = False
        self.bitblt_raises = False

    def GetWindowRect(self, hwnd):
        self.events.append("GetWindowRect")
        return self.rect

    def GetWindowDC(self, hwnd):
        self.events.append("GetWindowDC")
        return 1001

    def ReleaseDC(self, hwnd, hwnd_dc):
        self.events.append("ReleaseDC")
        self.release_calls.append((hwnd, hwnd_dc))

    def DeleteObject(self, handle):
        self.events.append("DeleteObject")
        # 2.2：删除时位图不得仍被任何 DC 选中
        for dc in self.ui.dcs:
            if dc.current is not None and dc.current.handle == handle:
                self.delete_while_selected = True

    def GetWindowText(self, hwnd):
        return self.window_text


@pytest.fixture
def fake_gdi(monkeypatch):
    """把 screenshot_core 命名空间中的 win32gui / win32ui 换成假实现。"""
    import modules.screenshot.screenshot_core as sc

    ui = _FakeWin32Ui()
    gui = _FakeWin32Gui(ui)
    ui.gui = gui
    monkeypatch.setattr(sc, "win32gui", gui)
    monkeypatch.setattr(sc, "win32ui", ui)
    return gui


def _core(tmp_path):
    core = ScreenshotCore()
    core.output_dir = tmp_path
    return core


def _rgb32_pixel(r, g, b):
    """Format_RGB32 像素（0xffRRGGBB）小端内存字节：BB GG RR FF。"""
    return bytes([b, g, r, 0xFF])


# ── 2.1 异常路径 GDI 泄漏 ─────────────────────────────────────────────

def test_capture_window_releases_gdi_on_exception(fake_gdi, tmp_path):
    """BitBlt 抛异常时，ReleaseDC / DeleteDC / DeleteObject 仍必须执行。"""
    fake_gdi.bitblt_raises = True
    core = _core(tmp_path)

    result = core.capture_window(0x1234, output_filename="boom")

    assert result is None
    assert (0x1234, 1001) in fake_gdi.release_calls, (
        "异常路径必须 ReleaseDC，否则每次失败泄漏 2 个 GDI 对象")
    assert "DeleteDC(save)" in fake_gdi.events, "异常路径必须释放 save_dc"
    assert "DeleteDC(mfc)" in fake_gdi.events, "异常路径必须释放 mfc_dc"
    assert "DeleteObject" in fake_gdi.events, "异常路径必须删除位图"


# ── 2.2 DeleteObject 前未解除选中 ─────────────────────────────────────

def test_capture_window_deselects_bitmap_before_delete(fake_gdi, tmp_path):
    """DeleteObject 前必须先解除位图选中（还原旧对象）。"""
    core = _core(tmp_path)

    result = core.capture_window(0x1234, output_filename="ok")

    assert result is not None
    assert fake_gdi.delete_while_selected is False, (
        "DeleteObject 时位图仍被 DC 选中必然失败，必须先 SelectObject 还原")


# ── 2.3 bottom-up 扫描行导致图像上下颠倒 ──────────────────────────────

def test_capture_window_mirrors_bottom_up_bits(fake_gdi, tmp_path):
    """GetBitmapBits(True) 返回 bottom-up 扫描行，保存的图像必须正立。

    构造 2x2 图像：上红下蓝。bottom-up 字节序先给底行（蓝）再给顶行（红）。
    未修正时 QImage 顶部是蓝（上下颠倒）；mirrored() 后顶部应为红。
    """
    fake_gdi.rect = (0, 0, 2, 2)
    top_red = _rgb32_pixel(255, 0, 0)
    bottom_blue = _rgb32_pixel(0, 0, 255)
    fake_gdi.ui.next_bits = bottom_blue + bottom_blue + top_red + top_red

    core = _core(tmp_path)
    result = core.capture_window(0x1234, output_filename="orient")

    assert result is not None
    img = QImage(result)
    assert (img.width(), img.height()) == (2, 2)
    top = img.pixelColor(0, 0)
    bottom = img.pixelColor(0, 1)
    assert top.red() == 255 and top.blue() == 0, (
        f"顶行应为红（正立），实际 top=({top.red()},{top.green()},{top.blue()})")
    assert bottom.blue() == 255 and bottom.red() == 0, (
        f"底行应为蓝，实际 bottom=({bottom.red()},{bottom.green()},{bottom.blue()})")