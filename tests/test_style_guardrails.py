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


def test_audit_private_palette_rule_catches_rss_style_defs(tmp_path):
    """回归锁定审计私有调色板规则：_xxx_colors() 定义必须被审计捕获。

    原护栏 test_rss_palette_subset_of_theme_palette 是同义反复——
    rss_palette() 字面返回 dict(theme_palette())，断言恒真、永不失败。
    真正防私有调色板回潮的机制是审计的 private_palette 规则（RE_PALETTE），
    此处直接回归锁定该规则本身。
    """
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "audit_styles", repo / "scripts" / "audit_styles.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    evil = tmp_path / "evil_palette.py"
    evil.write_text(
        "def _rss_palette_colors():\n"
        "    return {'rss_accent': '#000000'}\n",
        encoding="utf-8")
    hits = mod.audit_file(str(evil))
    assert any(h["rule"] == "private_palette" for h in hits), \
        f"审计未捕获私有调色板定义: {hits}"


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