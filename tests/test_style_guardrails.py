"""运行时护栏：
1) 主题切换后，工厂控件 QSS 必须全部来自新主题调色板（无旧主题残留）。
2) 字体缩放 1.6x 下，按钮文字完整可见（不截断）。
"""
import re

import pytest

from conftest import _force_dark, _restore_dark
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _qss_colors(qss):
    """提取 QSS 中出现的所有 #hex 与 rgba(...)。"""
    hexes = re.findall(r"#[0-9a-fA-F]{6}\b", qss)
    return set(hexes)


def _palette_colors(p):
    """调色板中全部 #hex 值集合。"""
    return {v for v in p.values() if isinstance(v, str) and v.startswith("#")}


def test_theme_switch_no_stale_colors_on_factory_widgets(_qapp):
    """切到暗色后，工厂控件 QSS 中不得残留亮色专有色。"""
    from core.theme.tokens import theme_palette
    from ui.widgets import make_button, make_label, make_status_chip
    try:
        _force_dark(False)
        light_only = _palette_colors(theme_palette())
        _force_dark(True)
        dark_only = _palette_colors(theme_palette())
        stale = light_only - dark_only  # 亮色专有、暗色没有的颜色
        assert stale, "测试前提：明暗调色板必须有差异色"

        # 用暗色主题创建全套工厂控件，遍历其 QSS 断言无亮色残留
        _force_dark(True)
        widgets = [
            make_button("确定", kind="primary"),
            make_button("幽灵", kind="ghost"),
            make_label("标题", role="title"),
            make_status_chip("磁链", kind="torrent"),
        ]
        for w in widgets:
            found = _qss_colors(w.styleSheet()) & stale
            assert not found, f"{type(w).__name__} 残留亮色: {found}"
    finally:
        _restore_dark()


def test_font_scale_16_button_text_fits(_qapp):
    """1.6x 缩放下按钮文字+内边距必须装得下（截断护栏）。"""
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    from ui.widgets import make_button
    ConfigHolder.scale = 1.6
    try:
        btn = make_button("保存设置", kind="default")
        btn.show()
        fm = QtGui.QFontMetrics(btn.font())
        text_w = fm.horizontalAdvance(btn.text())
        pad_w = int(sizing()["btn_padding_md"].split()[1].rstrip("px")) * 2
        assert btn.width() >= text_w + pad_w + 2, \
            f"文字 {text_w}px + 内边距 {pad_w}px 超出按钮宽 {btn.width()}px"
        assert btn.height() >= fm.height() + 4, \
            f"文字高 {fm.height()}px 超出按钮高 {btn.height()}px"
    finally:
        ConfigHolder.scale = 1.0
        btn.close()


def _load_audit_module():
    """加载 scripts/audit_styles.py（与私有调色板测试同一模式）。"""
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "audit_styles", repo / "scripts" / "audit_styles.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tbar_style_rule_catches_fixed_without_qss(tmp_path):
    """T9：迁移标题栏控件 setFixedWidth 但未配套 setStyleSheet → 命中。

    回归锁定"全部"下拉框白色弹片盒 + 下边框截断事故：combo 只改尺寸、
    保留 qfluentwidgets 内嵌 QSS（内容盒 31px > 28px 物理高）正是根因。
    """
    mod = _load_audit_module()
    f = tmp_path / "page_lifecycle.py"
    f.write_text(
        "class X:\n"
        "    def build(self):\n"
        "        self.combo_search_field.setFixedWidth(80)\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    assert any(h["rule"] == "tbar_style_missing" for h in hits), hits


def test_tbar_style_rule_accepts_direct_qss(tmp_path):
    """T10：setFixedWidth 后紧接 setStyleSheet → 不命中（合规配对）。"""
    mod = _load_audit_module()
    f = tmp_path / "page_lifecycle.py"
    f.write_text(
        "class X:\n"
        "    def build(self):\n"
        "        self.combo_search_field.setFixedWidth(80)\n"
        "        self.combo_search_field.setStyleSheet('QPushButton{}')\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    assert not any(h["rule"] == "tbar_style_missing" for h in hits), hits


def test_tbar_style_rule_accepts_batch_loop_qss(tmp_path):
    """T11：批量循环体内 setStyleSheet 覆盖元组全部控件 → 不命中。"""
    mod = _load_audit_module()
    f = tmp_path / "page_lifecycle.py"
    f.write_text(
        "class X:\n"
        "    def build(self):\n"
        "        for b in (btn_date_filter, btn_filter, btn_read_ops):\n"
        "            b.setFixedHeight(28)\n"
        "            b.setStyleSheet(qss)\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    assert not any(h["rule"] == "tbar_style_missing" for h in hits), hits


def test_tbar_style_rule_ignores_search_input(tmp_path):
    """T12：search_input 不在名单（SearchLineEdit 自带框是设计）→ 不命中。"""
    mod = _load_audit_module()
    f = tmp_path / "page_lifecycle.py"
    f.write_text(
        "class X:\n"
        "    def build(self):\n"
        "        self.search_input.setFixedWidth(150)\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    assert not any(h["rule"] == "tbar_style_missing" for h in hits), hits


def test_tbar_style_rule_clean_on_real_page_lifecycle():
    """T13：线上 page_lifecycle.py 不得有任何 tbar_style_missing 违规。"""
    mod = _load_audit_module()
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    src = repo / "modules" / "rss_aggregator" / "page_lifecycle.py"
    hits = mod.audit_file(str(src))
    assert not any(h["rule"] == "tbar_style_missing" for h in hits), \
        [h for h in hits if h["rule"] == "tbar_style_missing"]


def test_rgba_literal_rule_catches_hardcoded_rgba(tmp_path):
    """T14：rgba 字面量硬编码必须被审计捕获（含大小写与空格变体）。"""
    mod = _load_audit_module()
    f = tmp_path / "evil_rgba.py"
    f.write_text(
        "qss = 'background: rgba(255,0,0,0.5)'\n"
        "qss2 = 'background: RGBA( 0, 0, 0, 0.50 )'\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    rgba_hits = [h for h in hits if h["rule"] == "rgba_color"]
    assert len(rgba_hits) == 2, f"审计未捕获全部 rgba 字面量: {hits}"


def test_rgb_literal_rule_catches_hardcoded_rgb(tmp_path):
    """T15：rgb 三通道字面量同样必须被审计捕获。"""
    mod = _load_audit_module()
    f = tmp_path / "evil_rgb.py"
    f.write_text(
        "qss = 'color: rgb(255, 0, 0)'\n",
        encoding="utf-8")
    hits = mod.audit_file(str(f))
    assert any(h["rule"] == "rgba_color" for h in hits), \
        f"审计未捕获 rgb 字面量: {hits}"


def test_rgba_rule_ignores_whitelisted_tokens():
    """T16：白名单文件（core/theme/tokens.py 定义令牌本身）不误报。"""
    mod = _load_audit_module()
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    src = repo / "core" / "theme" / "tokens.py"
    hits = mod.audit_file(str(src))
    assert not any(h["rule"] == "rgba_color" for h in hits), \
        [h for h in hits if h["rule"] == "rgba_color"]


# ── C6③ 用户可选字体族（todo 14）──────────────────────────────────────

def test_default_config_has_font_family():
    """DEFAULT_CONFIG 必须包含 ui.font_family，且为非空字符串。"""
    from core.constants import DEFAULT_CONFIG
    family = DEFAULT_CONFIG["ui"]["font_family"]
    assert isinstance(family, str) and family.strip()


def test_font_family_config_roundtrip(tmp_path):
    """ui.font_family 写入 settings.json 后可往返读取；未写入时回落到 DEFAULT_CONFIG 默认值。"""
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    path = str(tmp_path / "settings.json")
    cfg = AppConfig(path, defaults=DEFAULT_CONFIG)
    assert cfg.get("ui.font_family") == DEFAULT_CONFIG["ui"]["font_family"]
    cfg.set("ui.font_family", "Microsoft YaHei UI")
    cfg2 = AppConfig(path, defaults=DEFAULT_CONFIG)
    assert cfg2.get("ui.font_family") == "Microsoft YaHei UI"


def test_font_family_applied_to_qapplication(qapp, tmp_path):
    """happy：把 ui.font_family 设为真实字体族（offscreen 无字体库时用通用族名），
    经 config → ConfigHolder.families → apply_font_scale 后，
    QApplication.font().family() 必须等于该族。"""
    from PySide6.QtGui import QFontDatabase
    from core.config import AppConfig
    from core.constants import DEFAULT_CONFIG
    from core.theme.font import ConfigHolder, apply_font_scale
    from qfluentwidgets.common.font import fontFamilies, setFontFamilies as _restore_families
    families = QFontDatabase.families()
    chosen = families[0] if families else "Arial"
    cfg = AppConfig(path=str(tmp_path / "settings.json"), defaults=DEFAULT_CONFIG)
    cfg.set("ui.font_family", chosen)
    font_family = cfg.get("ui.font_family", "Microsoft YaHei")
    orig_font = qapp.font()
    orig_qff = fontFamilies()
    ConfigHolder.families = [font_family, "Segoe UI", "PingFang SC"]
    try:
        apply_font_scale(1.0)
        assert qapp.font().family() == chosen
    finally:
        qapp.setFont(orig_font)
        _restore_families(orig_qff)
        ConfigHolder.families = ["Microsoft YaHei", "Segoe UI", "PingFang SC"]
        ConfigHolder.scale = 1.0


def test_font_family_falls_back_on_missing_family(qapp):
    """failure：ui.font_family 指向不存在的字体族时，应用不抛异常，
    且解析出的实际字体族不是该不存在的族（回退到可用字体）。"""
    from PySide6.QtGui import QFontInfo
    from core.theme.font import ConfigHolder, apply_font_scale
    from qfluentwidgets.common.font import fontFamilies, setFontFamilies as _restore_families
    orig_font = qapp.font()
    orig_qff = fontFamilies()
    ConfigHolder.families = ["__no_such_family__", "Segoe UI", "PingFang SC"]
    try:
        scale = apply_font_scale(1.0)  # 不得抛异常
        assert scale == 1.0
        resolved = QFontInfo(qapp.font()).family()
        assert resolved != "__no_such_family__"
    finally:
        qapp.setFont(orig_font)
        _restore_families(orig_qff)
        ConfigHolder.families = ["Microsoft YaHei", "Segoe UI", "PingFang SC"]
        ConfigHolder.scale = 1.0