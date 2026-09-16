"""Task 11: collect_info 运行配置字段 + validate_info 校验 + 页面校验结果区。

- validate_info(info) -> list[str]：纯函数，空列表 = 全部正常，顺序稳定，绝不抛异常。
- collect_info(config=None)：追加 开机自启/主题/窗口尺寸/截图热键 四键（config 为 None 时
  主题/窗口尺寸/截图热键 显示 "—"，开机自启仍计算）。
- 子进程冒烟：make_info_widget(None, fake_config) 渲染校验结果区（"正常" 或 chips）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.sys_info import collect_info, validate_info


def _normal_dict() -> dict[str, object]:
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
        self._values = {"ui.theme": "dark", "window.width": 1280, "window.height": 720}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def module_setting(self, module_id, key, default=False):
        return self._hotkey


def test_collect_info_with_config(monkeypatch):
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    info = collect_info(_FakeConfig())
    assert info["开机自启"] == "已启用"
    assert info["主题"] == "深色"
    assert info["窗口尺寸"] == "1280×720"
    assert info["截图热键"] == "已启用"


def test_collect_info_without_config(monkeypatch):
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    info = collect_info(None)
    assert info["开机自启"] == "已启用"
    assert info["主题"] == "—"
    assert info["窗口尺寸"] == "—"
    assert info["截图热键"] == "—"


def test_collect_info_window_size_from_default_config(monkeypatch, tmp_path):
    """真实 DEFAULT_CONFIG（window.width/height）下窗口尺寸返回具体数值而非"—"。"""
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    from core.config import AppConfig
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    info = collect_info(cfg)
    assert info["窗口尺寸"] == "1280×800"


def test_collect_info_window_size_legacy_ui_keys(monkeypatch):
    """旧键 ui.width/ui.height 仍兼容（既有用户数据不破坏）。"""
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    cfg = _FakeConfig()
    cfg._values = {"ui.theme": "dark", "ui.width": 1024, "ui.height": 768}
    info = collect_info(cfg)
    assert info["窗口尺寸"] == "1024×768"


def test_collect_info_theme_auto_resolves(monkeypatch):
    """ui.theme="auto" 时主题显示解析后的实际主题（浅色/深色），而非 "auto"。"""
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    cfg = _FakeConfig()
    cfg._values = {"ui.theme": "auto", "window.width": 1280, "window.height": 720}
    info = collect_info(cfg)
    assert info["主题"] in ("浅色", "深色")


def test_collect_info_theme_light_resolves(monkeypatch):
    """ui.theme="light" 时主题显示「浅色」。"""
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    cfg = _FakeConfig()
    cfg._values = {"ui.theme": "light", "window.width": 1280, "window.height": 720}
    info = collect_info(cfg)
    assert info["主题"] == "浅色"


def test_collect_info_hotkey_label_and_value(monkeypatch):
    """热键项标签为「截图热键」，值为「已启用/未启用」（无「截图: 」前缀）。"""
    monkeypatch.setattr("core.autostart.autostart_enabled", lambda: True)
    on = collect_info(_FakeConfig(hotkey=True))
    assert on["截图热键"] == "已启用"
    assert "截图: " not in on["截图热键"]
    off = collect_info(_FakeConfig(hotkey=False))
    assert off["截图热键"] == "未启用"


def test_validate_info_full_21_keys_passes():
    """collect_info 的 21 个键全部正常时 validate_info 返回空列表。"""
    info = _normal_dict()
    info.update({
        "主机名": "DESKTOP-TEST",
        "系统": "Windows 11",
        "版本": "10.0.22631",
        "机器": "AMD64",
        "物理核心": 16,
        "逻辑核心": 32,
        "内存总量": "32.0 GB",
        "系统盘": "C:\\ 500.0 GB (50% 已用)",
        "Python版本": "3.11.9",
        "PySide6版本": "6.6.2",
        "qfluentwidgets版本": "1.5.0",
        "网络适配器": "以太网: 192.168.1.1",
        "开机自启": "已启用",
        "主题": "浅色",
        "窗口尺寸": "1280×800",
        "截图热键": "已启用",
    })
    assert len(info) == 21
    assert validate_info(info) == []


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