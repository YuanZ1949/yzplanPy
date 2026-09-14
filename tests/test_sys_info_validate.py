"""Task 11: collect_info 运行配置字段 + validate_info 校验 + 页面校验结果区。

- validate_info(info) -> list[str]：纯函数，空列表 = 全部正常，顺序稳定，绝不抛异常。
- collect_info(config=None)：追加 开机自启/主题/窗口尺寸/全局热键 四键（config 为 None 时
  主题/窗口尺寸/全局热键 显示 "—"，开机自启仍计算）。
- 子进程冒烟：make_info_widget(None, fake_config) 渲染校验结果区（"正常" 或 chips）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.sys_info import collect_info, validate_info


def _normal_dict():
    """全部字段正常：GPU/处理器 非空、内存 used<=total、IO 非负、时间可解析、无"未知"。"""
    return {
        "GPU": "NVIDIA GeForce RTX 4090",
        "处理器": "Intel(R) Core(TM) i9-13900K",
        "内存使用": "8.0 GB / 16.0 GB (50%)",
        "磁盘IO": "读 1.0 GB / 写 5.0 MB",
        "系统启动时间": "2026-09-14 08:00:00",
    }


def test_validate_info_normal_returns_empty():
    assert validate_info(_normal_dict()) == []


def test_validate_info_memory_over_total():
    d = _normal_dict()
    d["内存使用"] = "20.0 GB / 8.0 GB (250%)"
    assert "内存使用超过总量" in validate_info(d)


def test_validate_info_io_negative():
    d = _normal_dict()
    d["磁盘IO"] = "读 -1.0 GB / 写 5 MB"
    assert "磁盘IO 出现负值" in validate_info(d)


def test_validate_info_gpu_unknown_and_empty():
    d = _normal_dict()
    d["GPU"] = "未知"
    assert "GPU 为未知" in validate_info(d)
    d2 = _normal_dict()
    d2["GPU"] = ""
    assert "GPU 为空" in validate_info(d2)


def test_validate_info_boot_time_invalid():
    d = _normal_dict()
    d["系统启动时间"] = "not-a-date"
    assert "系统启动时间格式非法" in validate_info(d)


class _FakeConfig:
    """AppConfig 最小替身：get 支持点路径，module_setting 固定返回。"""

    def __init__(self, hotkey=True):
        self._hotkey = hotkey
        self._values = {"ui.theme": "dark", "ui.width": 1280, "ui.height": 720}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def module_setting(self, module_id, key, default=False):
        return self._hotkey


def test_collect_info_with_config(monkeypatch):
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    info = collect_info(_FakeConfig())
    assert info["开机自启"] == "已启用"
    assert info["主题"] == "dark"
    assert info["窗口尺寸"] == "1280×720"
    assert info["全局热键"] == "截图: 已启用"


def test_collect_info_without_config(monkeypatch):
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    info = collect_info(None)
    assert info["开机自启"] == "已启用"
    assert info["主题"] == "—"
    assert info["窗口尺寸"] == "—"
    assert info["全局热键"] == "—"


def test_make_info_widget_validation_smoke_subprocess():
    """Subprocess isolation: 校验结果区渲染冒烟 (0xC0000005 guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_make_info_widget_validation_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_sys_info_validate.py::{child_name}",
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
    assert "SYSINFO_VALIDATE_OK" in result.stdout.decode(errors="replace")


def test_make_info_widget_validation_smoke_child():
    """Child: make_info_widget(None, fake_config) → show → 校验区含 "正常" 或 chips。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from modules.sys_info_widget import make_info_widget

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    w = make_info_widget(None, _FakeConfig())
    w.show()
    app.processEvents()
    labels = [l.text() for l in w.findChildren(QtWidgets.QLabel)]
    assert any(t == "正常" or "为" in t or "等" in t for t in labels), labels
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("SYSINFO_VALIDATE_OK")