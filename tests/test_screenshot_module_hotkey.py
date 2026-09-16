"""截图模块管理页热键回调测试。

缺陷：modules/screenshot/module.py create_settings_widget 传 hotkey_callback=None
→ screenshot_settings.py _apply_hotkey 短路 → 模块管理页保存热键不注册。
本测试锁定修复：回调非 None、保存触发 register_hotkey/unregister_hotkey、
且可通过 is_hotkey_registered 观察。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139）。
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication
QKeySequence = QtGui.QKeySequence

from core.config import AppConfig
from modules.screenshot.module import Module

# 测试用唯一快捷键，避免与系统/其他应用冲突导致 RegisterHotKey 失败
TEST_HOTKEY = "Ctrl+Alt+Shift+F12"


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _context(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    return type("Ctx", (), {"config": cfg, "host_window": None, "app": _app()})()


def _make_widget(tmp_path):
    ctx = _context(tmp_path)
    mod = Module(ctx)
    widget = mod.create_settings_widget(None)
    return ctx, mod, widget


def test_create_settings_widget_hotkey_callback_not_none(tmp_path):
    """create_settings_widget 返回的 widget 热键回调必须非 None。"""
    _, _, widget = _make_widget(tmp_path)
    assert widget._hotkey_callback is not None, (
        "模块管理页热键回调不应为 None，否则 _apply_hotkey 短路导致热键无法注册")
    widget.close()


def test_save_with_hotkey_enabled_calls_register_hotkey_and_writes_config(
        tmp_path, monkeypatch):
    """启用热键保存 → 调用 core.register_hotkey 并写入配置。"""
    ctx, mod, widget = _make_widget(tmp_path)
    calls = []
    monkeypatch.setattr(
        mod.core, "register_hotkey",
        lambda seq, cb, app=None: calls.append((seq.toString(), cb)) or True)

    widget.hotkey_enable_cb.setChecked(True)
    widget.hotkey_seq_edit.setKeySequence(QKeySequence(TEST_HOTKEY))
    widget.save_settings()

    assert len(calls) == 1, f"register_hotkey 应被调用 1 次，实际 {len(calls)}"
    seq_str, cb = calls[0]
    assert seq_str == TEST_HOTKEY
    assert cb is widget._hotkey_callback
    assert ctx.config.module_setting("screenshot", "hotkey_enabled") is True
    assert ctx.config.module_setting("screenshot", "hotkey_sequence") == TEST_HOTKEY
    widget.close()


def test_save_with_hotkey_disabled_calls_unregister_hotkey(tmp_path, monkeypatch):
    """先启用保存（注册）再禁用保存 → 调用 core.unregister_hotkey。"""
    _, mod, widget = _make_widget(tmp_path)
    unreg = []
    monkeypatch.setattr(mod.core, "register_hotkey", lambda seq, cb, app=None: True)
    monkeypatch.setattr(mod.core, "unregister_hotkey", lambda: unreg.append(1))

    widget.hotkey_enable_cb.setChecked(True)
    widget.save_settings()
    assert unreg == []

    widget.hotkey_enable_cb.setChecked(False)
    widget.save_settings()
    assert unreg == [1], "禁用热键保存应调用 core.unregister_hotkey"
    widget.close()


def test_save_twice_with_hotkey_enabled_unregisters_before_register(
        tmp_path, monkeypatch):
    """连续两次启用保存：第二次先注销再注册，避免重复注册同一 hotkey_id。"""
    _, mod, widget = _make_widget(tmp_path)
    reg = []
    unreg = []
    monkeypatch.setattr(
        mod.core, "register_hotkey",
        lambda seq, cb, app=None: reg.append(1) or True)
    monkeypatch.setattr(mod.core, "unregister_hotkey", lambda: unreg.append(1))

    widget.hotkey_enable_cb.setChecked(True)
    widget.save_settings()
    widget.save_settings()

    assert len(reg) == 2, f"register_hotkey 应调用 2 次，实际 {len(reg)}"
    assert len(unreg) == 1, f"第二次保存应先注销再注册，实际注销 {len(unreg)} 次"
    widget.close()


def test_save_with_hotkey_enabled_registers_real_hotkey(tmp_path):
    """真实注册：保存启用热键后 core.is_hotkey_registered() 为 True。"""
    _, mod, widget = _make_widget(tmp_path)
    widget.hotkey_enable_cb.setChecked(True)
    widget.hotkey_seq_edit.setKeySequence(QKeySequence(TEST_HOTKEY))
    widget.save_settings()
    try:
        assert mod.core.is_hotkey_registered() is True, (
            "保存启用热键后应真实注册全局快捷键")
    finally:
        mod.core.unregister_hotkey()
    widget.close()