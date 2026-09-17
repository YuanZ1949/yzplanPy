"""静态扫描：四类违规规则命中与豁免、基线 diff 机制。"""


def _audit_text(tmp_path, text, fname="sample.py"):
    f = tmp_path / fname
    f.write_text(text, encoding="utf-8")
    return f


def _run_audit_single(path):
    """对单文件跑 audit_file（避免 CLI 全仓依赖）。"""
    from scripts.audit_styles import audit_file
    return audit_file(str(path))


def test_detects_fixed_height(tmp_path):
    f = _audit_text(tmp_path, "from PySide6 import QtWidgets\n\nb = QtWidgets.QPushButton()\nb.setFixedHeight(28)\n")
    hits = _run_audit_single(f)
    assert any(h["rule"] == "fixed_size" for h in hits)


def test_detects_hardcoded_hex(tmp_path):
    f = _audit_text(tmp_path, 'b.setStyleSheet("QPushButton { background: #ff0000; }")\n')
    hits = _run_audit_single(f)
    assert any(h["rule"] == "hex_color" for h in hits)


def test_detects_private_palette(tmp_path):
    f = _audit_text(tmp_path, "def _my_colors():\n    return {'accent': '#3aa6ff'}\n")
    hits = _run_audit_single(f)
    assert any(h["rule"] == "private_palette" for h in hits)


def test_whitelisted_files_exempt(tmp_path):
    """core/theme/tokens.py 与 ui/widgets.py 是唯一允许裸 hex 的代码区。"""
    from scripts.audit_styles import WHITELIST
    assert "core/theme/tokens.py" in WHITELIST
    assert "ui/widgets.py" in WHITELIST


SIZE_QSS_SAMPLE = 'padding: 4px 10px; font-size: 11px;'  # 尺寸字面量应捕获


def test_size_literal_rule_catches_qss_px(tmp_path):
    from scripts.audit_styles import Rule
    f = _audit_text(tmp_path, f'w.setStyleSheet("QLineEdit {{ {SIZE_QSS_SAMPLE} }}")\n')
    hits = _run_audit_single(f)
    assert any(h["rule"] == Rule.SIZE_LITERAL.value for h in hits)


def test_audit_file_cross_drive_path_does_not_crash(tmp_path, monkeypatch):
    """跨盘符路径（CI: REPO 在 D:、pytest tmp_path 在 C:）不应抛 ValueError（回归）。

    os.path.relpath 在 path 与 start 位于不同盘符时抛 ValueError；CI 的
    windows-latest 工作区在 D:，而 pytest tmp_path 在 C:，导致 audit_file 崩溃，
    使 test_style_audit.py / test_style_audit_exempt.py 全部失败。
    """
    import scripts.audit_styles as audit_styles
    monkeypatch.setattr(audit_styles, "REPO", "Z:\\nonexistent\\repo")
    f = _audit_text(tmp_path, 'b.setStyleSheet("QPushButton { background: #ff0000; }")\n')
    hits = audit_styles.audit_file(str(f))
    assert any(h["rule"] == "hex_color" for h in hits), hits