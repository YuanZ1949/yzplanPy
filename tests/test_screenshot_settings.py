"""截图模块设置页与配置持久化测试。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

# 必须走 core.qt_bootstrap.import_qt()：Windows 冷进程直接 import PySide6
# 会触发 Qt6Core 的 icuuc.dll 解析 bug（WinError 127 / 0xc0000139），
# qt_bootstrap 模块级 _preload_icu() 在进程内预载 ICU DLL 后 Qt 才能加载。
# 本文件的子进程测试（test_settings_widget_save_smoke_child）是全新进程，
# 直接 import 必然崩溃；其余测试文件因全量运行时 PySide6 已先行加载而幸免。
from core.qt_bootstrap import import_qt

_, _, _, QtWidgets = import_qt()

QApplication = QtWidgets.QApplication
QTabWidget = QtWidgets.QTabWidget
QLineEdit = QtWidgets.QLineEdit
QComboBox = QtWidgets.QComboBox
QPushButton = QtWidgets.QPushButton
QCheckBox = QtWidgets.QCheckBox

from core.config import AppConfig
from modules.screenshot.screenshot_core import ScreenshotCore
from modules.screenshot.screenshot_ui import ScreenshotWidget
from modules.screenshot.screenshot_settings import _SettingsTab
from modules.screenshot.module import Module


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _context(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    return type("Ctx", (), {"config": cfg, "host_window": None, "app": _app()})()


def _find_tab_widget(widget):
    return widget.findChild(QTabWidget)


def test_settings_tab_present_with_fields(tmp_path):
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    assert tabs is not None
    assert tabs.count() == 5
    assert tabs.tabText(4) == "设置"

    settings = tabs.widget(4)
    assert isinstance(settings, _SettingsTab)
    assert isinstance(settings.save_dir_input, QLineEdit)
    assert isinstance(settings.format_combo, QComboBox)
    assert settings.format_combo.itemText(0) == "PNG"
    assert settings.format_combo.itemText(1) == "JPG"
    assert isinstance(settings.template_input, QLineEdit)
    assert isinstance(settings.save_settings_btn, QPushButton)
    assert isinstance(settings.hotkey_enable_cb, QCheckBox)
    w.close()


def test_save_settings_writes_config_and_applies_to_core(tmp_path):
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)
    tabs = _find_tab_widget(w)
    settings = tabs.widget(4)

    save_dir = str(tmp_path / "shots")
    settings.save_dir_input.setText(save_dir)
    settings.format_combo.setCurrentText("JPG")
    settings.template_input.setText("cap_%Y%m%d")

    settings.save_settings()

    cfg = ctx.config
    assert cfg.module_setting("screenshot", "save_dir") == save_dir
    assert cfg.module_setting("screenshot", "format") == "JPG"
    assert cfg.module_setting("screenshot", "filename_template") == "cap_%Y%m%d"

    assert w.core.output_dir == Path(save_dir)
    assert w.core._format == "JPG"
    assert w.core._filename_template == "cap_%Y%m%d"
    w.close()


def test_settings_tab_standalone_without_context():
    """_SettingsTab 无 context 直接构建不崩（模块管理页入口）。"""
    tab = _SettingsTab()
    assert isinstance(tab.save_dir_input, QLineEdit)
    assert isinstance(tab.hotkey_enable_cb, QCheckBox)
    tab.close()


def test_settings_tab_loads_from_config(tmp_path):
    """有 context 时 _load_settings 从假 config 填充值正确。"""
    ctx = _context(tmp_path)
    ctx.config.set_module_config("screenshot", {
        "save_dir": str(tmp_path / "custom"),
        "format": "JPG",
        "filename_template": "shot_%H%M%S",
        "hotkey_enabled": True,
        "hotkey_sequence": "Ctrl+Alt+P",
        "hotkey_mode": "delayed",
        "hotkey_delay": 5,
    })
    tab = _SettingsTab(context=ctx)
    assert tab.save_dir_input.text() == str(tmp_path / "custom")
    assert tab.format_combo.currentText() == "JPG"
    assert tab.template_input.text() == "shot_%H%M%S"
    assert tab.hotkey_enable_cb.isChecked() is True
    assert tab.hotkey_seq_edit.keySequence().toString() == "Ctrl+Alt+P"
    assert tab.hotkey_delayed_rb.isChecked() is True
    assert tab.hotkey_delay_spin.value() == 5
    tab.close()


def test_core_applies_config_on_init(tmp_path):
    cfg = AppConfig(path=str(tmp_path / "settings.json"))
    cfg.set_module_config("screenshot", {
        "save_dir": str(tmp_path / "custom"),
        "format": "JPG",
        "filename_template": "shot_%H%M%S",
    })

    core = ScreenshotCore(config=cfg)
    assert core.output_dir == Path(tmp_path / "custom")
    assert core._format == "JPG"
    assert core._filename_template == "shot_%H%M%S"


def test_core_defaults_without_config(tmp_path):
    core = ScreenshotCore()
    assert core._format == "PNG"
    assert core._filename_template == "screenshot_%Y%m%d_%H%M%S"
    assert core.output_dir.name == "screenshots"


def test_module_start_writes_enabled_flag(tmp_path):
    ctx = _context(tmp_path)
    mod = Module(ctx)
    mod.start()
    assert ctx.config.get("modules.screenshot.enabled") is True


def test_module_start_keeps_existing_enabled_flag(tmp_path):
    ctx = _context(tmp_path)
    ctx.config.set_module_enabled("screenshot", False)
    mod = Module(ctx)
    mod.start()
    assert ctx.config.get("modules.screenshot.enabled") is False


# ── 子进程冒烟：模块管理页"设置"面板保存生效 ───────────────────────────

def test_settings_widget_save_smoke_subprocess():
    """Subprocess isolation: create_settings_widget + save_settings persists config."""
    import subprocess
    import sys
    from pathlib import Path
    child_name = "test_settings_widget_save_smoke_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_screenshot_settings.py::{child_name}",
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
    assert "SETTINGS_SAVE_OK" in result.stdout.decode(errors="replace")


def test_settings_widget_save_smoke_child():
    """Child: create_settings_widget → save_settings → config persisted."""
    import tempfile
    from pathlib import Path

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    cfg = AppConfig(path=str(Path(tempfile.mkdtemp()) / "settings.json"))
    ctx = type("Ctx", (), {"config": cfg, "host_window": None, "app": app})()

    mod = Module(ctx)
    widget = mod.create_settings_widget(None)
    widget.save_dir_input.setText(str(Path(tempfile.mkdtemp()) / "shots"))
    widget.format_combo.setCurrentText("JPG")
    widget.save_settings()

    assert cfg.module_setting("screenshot", "format") == "JPG"
    assert cfg.module_setting("screenshot", "save_dir") != ""
    print("SETTINGS_SAVE_OK")