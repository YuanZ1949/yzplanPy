"""P-10 行内豁免机制：`# audit-exempt <reason>` 尾随注释使该行对所有规则豁免。

裁定（docs/superpowers/plans/2026-09-12-gui-style-migration-phase3.md P-10）：
QWebEngine JS 字符串与 MCP 跨进程色值数据不进入 Qt 令牌流，经行内豁免注释
跳过计数。豁免仅作用于被标注的那一行（无块级豁免）；无理由的 `# audit-exempt`
视为格式错误，不豁免。
"""
from scripts.audit_styles import audit_file


def _audit_text(tmp_path, text, fname="sample.py"):
    f = tmp_path / fname
    f.write_text(text, encoding="utf-8")
    return audit_file(str(f))


def test_exempt_comment_suppresses_hex_on_same_line(tmp_path):
    """带 `# audit-exempt: <reason>` 尾随注释的行，hex_color 不触发。"""
    hits = _audit_text(tmp_path, 'QColor("#1a73e8")  # audit-exempt: JS 桥接色值\n')
    assert not any(h["rule"] == "hex_color" for h in hits)


def test_same_literal_without_comment_fires(tmp_path):
    """同一字面量无豁免注释 → 正常触发。"""
    hits = _audit_text(tmp_path, 'QColor("#1a73e8")\n')
    assert any(h["rule"] == "hex_color" for h in hits)


def test_malformed_exempt_comment_without_reason_not_exempt(tmp_path):
    """`# audit-exempt` 无理由 → 格式错误，不豁免（仍触发）。"""
    hits = _audit_text(tmp_path, 'QColor("#1a73e8")  # audit-exempt\n')
    assert any(h["rule"] == "hex_color" for h in hits)


def test_exemption_does_not_affect_other_lines(tmp_path):
    """豁免只作用于被标注行，其他行照常计数。"""
    text = 'QColor("#1a73e8")  # audit-exempt: JS 桥接色值\nQColor("#ff0000")\n'
    hits = _audit_text(tmp_path, text)
    hex_hits = [h for h in hits if h["rule"] == "hex_color"]
    assert len(hex_hits) == 1
    assert hex_hits[0]["line"] == 2


def test_exemption_applies_to_all_rules_on_line(tmp_path):
    """同一行同时命中 hex/size_literal/hardcoded_qss，豁免后全部不计数。"""
    text = 'w.setStyleSheet("color:#ff0000; padding:4px 6px;")  # audit-exempt: 测试\n'
    hits = _audit_text(tmp_path, text)
    assert not any(h["rule"] in ("hex_color", "size_literal", "hardcoded_qss") for h in hits)


def test_exemption_suppresses_fixed_size(tmp_path):
    """fixed_size 规则同样受行内豁免约束。"""
    text = 'b.setFixedHeight(28)  # audit-exempt: 测试豁免\n'
    hits = _audit_text(tmp_path, text)
    assert not any(h["rule"] == "fixed_size" for h in hits)


def test_exemption_suppresses_private_palette_multiline(tmp_path):
    """多行私有调色板 def：豁免注释在 def 行 → private_palette 不触发；无注释则触发。"""
    exempt = 'def _foo_colors():  # audit-exempt: 测试多行豁免\n    return {"a": "#ff0000"}\n'
    assert not any(h["rule"] == "private_palette" for h in _audit_text(tmp_path, exempt))
    plain = 'def _foo_colors():\n    return {"a": "#ff0000"}\n'
    assert any(h["rule"] == "private_palette" for h in _audit_text(tmp_path, plain))
