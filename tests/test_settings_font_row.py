"""C6③ 设置页字体族选择行：外观卡片含字体族下拉，选择即写 ui.font_family。"""
import glob

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


class _Ctx:
    def __init__(self, config):
        self.config = config


@pytest.fixture
def _fonts(qapp):
    """offscreen 无字体库时注入系统字体，保证 QFontDatabase.families() 非空。

    Qt6 无 removeApplicationFont，注入的字体在会话内保留；对
    test_style_guardrails.py 的字体测试无影响（其断言对 families 内容不敏感）。
    """
    from PySide6.QtGui import QFontDatabase
    if not QFontDatabase.families():
        for ttf in glob.glob(r"C:\Windows\Fonts\*.ttf")[:3]:
            QFontDatabase.addApplicationFont(ttf)
    return QFontDatabase.families()


def _build_tab(qapp, tmp_path):
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    cfg = AppConfig(path=str(tmp_path / "settings.json"), defaults=DEFAULT_CONFIG)
    from ui.settings_tab import SettingsTab
    tab = SettingsTab(_Ctx(cfg))
    return tab, cfg


def test_appearance_page_has_font_family_row(_fonts, qapp, tmp_path):
    """外观卡片必须包含字体族行，下拉项数等于 QFontDatabase.families() 且 > 0。"""
    from PySide6.QtGui import QFontDatabase
    tab, _ = _build_tab(qapp, tmp_path)
    families = QFontDatabase.families()
    assert len(families) > 0
    assert tab.font_combo.count() == len(families)


def test_load_selects_configured_family(_fonts, qapp, tmp_path):
    """配置里已有 ui.font_family 时，构建设置页应回填到下拉当前项。"""
    from PySide6.QtGui import QFontDatabase
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    families = QFontDatabase.families()
    chosen = families[0]
    cfg = AppConfig(path=str(tmp_path / "settings.json"), defaults=DEFAULT_CONFIG)
    cfg.set("ui.font_family", chosen)
    from ui.settings_tab import SettingsTab
    tab = SettingsTab(_Ctx(cfg))
    assert tab.font_combo.currentText() == chosen


def test_selecting_font_family_writes_config(_fonts, qapp, tmp_path):
    """选择字体族后 ui.font_family 写入 settings.json、实时应用并往返读取。"""
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    from core.theme.font import ConfigHolder
    from qfluentwidgets.common.font import fontFamilies, setFontFamilies as _restore_families
    tab, cfg = _build_tab(qapp, tmp_path)
    cur = tab.font_combo.currentIndex()
    target = (cur + 1) % tab.font_combo.count()
    chosen = tab.font_combo.itemText(target)
    orig_families = ConfigHolder.families
    orig_font = qapp.font()
    orig_qff = fontFamilies()
    try:
        tab.font_combo.setCurrentIndex(target)
        assert cfg.get("ui.font_family") == chosen
        assert ConfigHolder.families[0] == chosen
        cfg2 = AppConfig(path=str(tmp_path / "settings.json"), defaults=DEFAULT_CONFIG)
        assert cfg2.get("ui.font_family") == chosen
    finally:
        qapp.setFont(orig_font)
        _restore_families(orig_qff)
        ConfigHolder.families = orig_families
        ConfigHolder.scale = 1.0