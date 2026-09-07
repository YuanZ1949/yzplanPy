"""截图模块设置页与配置持久化测试。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget, QLineEdit, QComboBox, QPushButton

from core.config import AppConfig
from modules.screenshot.screenshot_core import ScreenshotCore
from modules.screenshot.screenshot_ui import ScreenshotWidget
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

    assert isinstance(w.save_dir_input, QLineEdit)
    assert isinstance(w.format_combo, QComboBox)
    assert w.format_combo.itemText(0) == "PNG"
    assert w.format_combo.itemText(1) == "JPG"
    assert isinstance(w.template_input, QLineEdit)
    assert isinstance(w.save_settings_btn, QPushButton)
    w.close()


def test_save_settings_writes_config_and_applies_to_core(tmp_path):
    ctx = _context(tmp_path)
    w = ScreenshotWidget(context=ctx)

    save_dir = str(tmp_path / "shots")
    w.save_dir_input.setText(save_dir)
    w.format_combo.setCurrentText("JPG")
    w.template_input.setText("cap_%Y%m%d")

    w.save_settings()

    cfg = ctx.config
    assert cfg.module_setting("screenshot", "save_dir") == save_dir
    assert cfg.module_setting("screenshot", "format") == "JPG"
    assert cfg.module_setting("screenshot", "filename_template") == "cap_%Y%m%d"

    assert w.core.output_dir == Path(save_dir)
    assert w.core._format == "JPG"
    assert w.core._filename_template == "cap_%Y%m%d"
    w.close()


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