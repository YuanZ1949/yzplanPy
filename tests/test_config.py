import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import AppConfig


def test_config_roundtrip(tmp_path):
    path = str(tmp_path / "settings.json")
    cfg = AppConfig(path, defaults={"window": {"width": 960}, "close_to_tray": True})
    assert cfg.get("window.width") == 960
    cfg.set("window.width", 1200)
    cfg2 = AppConfig(path, defaults={"window": {"width": 960}})
    assert cfg2.get("window.width") == 1200


def test_module_flags(tmp_path):
    path = str(tmp_path / "settings.json")
    cfg = AppConfig(path, defaults={"modules": {}})
    assert cfg.module_enabled("whatever") is True
    cfg.set_module_enabled("x", False)
    assert cfg.module_enabled("x") is False
    cfg.set_module_config("x", {"interval": 60})
    assert cfg.module_setting("x", "interval") == 60