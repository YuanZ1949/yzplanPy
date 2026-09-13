"""GUI 样式静态审计：扫描五类违规，输出基线并 diff（新增违规即 fail）。

用法：
  python scripts/audit_styles.py --init    全仓扫描，写入 styles_audit_baseline.json
  python scripts/audit_styles.py --check   对比基线，新增违规 exit 1（CI/pre-commit）
  python scripts/audit_styles.py --report  打印全部违规

六类规则：
  fixed_size        setFixedHeight/setMinimumHeight 魔法数字
  hex_color         QSS 字符串中的 #hex 硬编码颜色
  rgba_color        QSS 字符串中的 rgba(...)/rgb(...) 硬编码颜色
  private_palette   模块内 def _xxx_colors() 私有调色板
  hardcoded_qss     模板内 setStyleSheet 拼接 hex/rgba 字面量
  size_literal      QSS 内数字 px 尺寸字面量（padding/width/height 等）
  tbar_style_missing 迁移标题栏控件设固定尺寸但未配套 setStyleSheet
                      （残留 qfluentwidgets 内嵌白色弹片盒/border-bottom）

行内豁免（P-10 非 Qt 渲染边界）：
  某行尾随注释匹配 `# audit-exempt <reason>`（正则 RE_EXEMPT）时，该行对所有
  规则豁免。仅作用于被标注的那一行——无块级/文件级豁免；无理由的
  `# audit-exempt` 视为格式错误，不豁免。用于 QWebEngine JS 字符串
  （浏览器沙箱内渲染，无 python 侧令牌访问）与 MCP 跨进程色值数据
  （下发给远端客户端，非本进程 Qt 样式）。裁定见
  docs/superpowers/plans/2026-09-12-gui-style-migration-phase3.md P-10。
"""
import argparse
import enum
import json
import os
import re
import sys


class Rule(enum.Enum):
    FIXED_SIZE = "fixed_size"
    HEX_COLOR = "hex_color"
    RGBA_COLOR = "rgba_color"
    PRIVATE_PALETTE = "private_palette"
    HARDCODED_QSS = "hardcoded_qss"
    SIZE_LITERAL = "size_literal"
    TBAR_STYLE_MISSING = "tbar_style_missing"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 唯一允许裸 hex / 固定尺寸的代码区（阶段 3 完成：qss 全局文件已收敛到令牌）
WHITELIST = {
    "core/theme/tokens.py",
    "ui/widgets.py",
    "scripts/audit_styles.py",
}

RE_FIXED = re.compile(r"set(?:Fixed|Minimum)Height\(\s*(\d+)\s*\)")
RE_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# rgba(...)/rgb(...) 字面量：`\b` 防误匹配函数名后缀，`\s*` 容忍
# `rgba(` 后空格，`\d` 确认括号内是数字字面量而非变量名（大小写不敏感）。
RE_RGBA = re.compile(r"\brgba?\s*\(\s*\d", re.I)
RE_PALETTE = re.compile(r"^\s*def\s+_(?:[a-z_]+_)?colors?\s*\(", re.M)
RE_QSS_HEX = re.compile(r'setStyleSheet\(\s*["\'].*?#[0-9a-fA-F]{6}', re.S)
# QSS 内数字 px 尺寸字面量（padding/width/height/border-radius/font-size 等）
RE_SIZE_LITERAL = re.compile(r"(?:padding|margin|width|height|border-radius|font-size|line-height):\s*\d+px", re.I)
# 行内豁免：`# audit-exempt <reason>`（理由必填，无理由不豁免）
RE_EXEMPT = re.compile(r"#\s*audit-exempt\b\s*[:：]?\s*.+")

# 迁移标题栏控件：qfluentwidgets 下拉/ComboBox 自带白色弹片盒 + border-bottom
# QSS（内容盒约 31px > 28px 物理高 → 下边框截断），setFixed*/setMinimum*
# 尺寸后必须配套 setStyleSheet 移除内嵌样式。search_input 有意排除
# （Fluent SearchLineEdit 自带输入框样式是设计的一部分）。
TBAR_EMBOSSED_CTRLS = frozenset(
    {"btn_date_filter", "btn_filter", "btn_read_ops", "btn_batch_ops",
     "btn_thumb", "combo_search_field"})
RE_TBAR_CTRL_FIXED = re.compile(r"(?:self\.)?([A-Za-z_]\w*)\.set(?:Fixed|Minimum)(?:Width|Height)\(")
RE_TBAR_CTRL_QSS = re.compile(r"(?:self\.)?([A-Za-z_]\w*)\.setStyleSheet\(")
RE_TBAR_FOR = re.compile(r"^\s*for\s+(\w+)\s+in\s*\(([^)]*)\)\s*:")


def _is_exempt(line):
    """该行是否带合法的行内豁免注释（P-10）。"""
    return bool(RE_EXEMPT.search(line))


def _audit_tbar_style(lines):
    """迁移标题栏控件必须配套 setStyleSheet（tbar_style_missing）。

    命中：名单控件出现 setFixed*/setMinimum* 尺寸调用，但既无直接
    `ctrl.setStyleSheet(`，也未出现在任何批量循环（`for <v> in (ctrls):`，
    循环体含 `<v>.setStyleSheet(`）。返回 [(行号, code)]。
    """
    fixed_of = {}
    qss_of = set()
    for i, line in enumerate(lines, 1):
        for m in RE_TBAR_CTRL_FIXED.finditer(line):
            fixed_of.setdefault(m.group(1), i)
        for m in RE_TBAR_CTRL_QSS.finditer(line):
            qss_of.add(m.group(1))
    loop_covered = set()
    for i, line in enumerate(lines):
        m = RE_TBAR_FOR.match(line)
        if not m:
            continue
        ctrls = [t.strip() for t in m.group(2).split(",") if t.strip()]
        if not ctrls:
            continue
        body_has_qss = False
        for j in range(i + 1, len(lines)):
            l = lines[j]
            if l.strip() and not l.startswith((" ", "\t")):
                break  # 循环体结束（缩进归位）
            if re.search(rf"\b{m.group(1)}\.setStyleSheet\(", l):
                body_has_qss = True
        if body_has_qss:
            loop_covered.update(ctrls)
    out = []
    for c in sorted(TBAR_EMBOSSED_CTRLS):
        if c in fixed_of and c not in qss_of and c not in loop_covered:
            out.append((fixed_of[c],
                        f"{c}: 设定固定尺寸但未配套 setStyleSheet"
                        f"（残留 qfluentwidgets 内嵌白底/边框 QSS）"))
    return out


def audit_file(path):
    """扫描单文件。返回违规列表 [{'file','line','rule','code'}]。"""
    rel = os.path.relpath(path, REPO).replace("\\", "/")
    if rel in WHITELIST or rel.startswith("tests/"):
        return []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    text = "\n".join(lines)
    hits = []

    for i, line in enumerate(lines, 1):
        if _is_exempt(line):
            continue
        if RE_FIXED.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.FIXED_SIZE.value, "code": line.strip()})
        if RE_HEX.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.HEX_COLOR.value, "code": line.strip()})
        if RE_RGBA.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.RGBA_COLOR.value, "code": line.strip()})
        if RE_SIZE_LITERAL.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.SIZE_LITERAL.value, "code": line.strip()})
    for m in RE_PALETTE.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        if _is_exempt(lines[ln - 1]):
            continue
        hits.append({"file": rel, "line": ln, "rule": Rule.PRIVATE_PALETTE.value, "code": m.group(0).strip()})
    for m in RE_QSS_HEX.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        if _is_exempt(lines[ln - 1]):
            continue
        hits.append({"file": rel, "line": ln, "rule": Rule.HARDCODED_QSS.value, "code": lines[ln - 1].strip()})
    # 迁移标题栏控件配套 QSS 审计（按 basename 判定，覆盖 tmp_path 测试文件）
    if os.path.basename(path) == "page_lifecycle.py":
        for ln, code in _audit_tbar_style(lines):
            hits.append({"file": rel, "line": ln, "rule": Rule.TBAR_STYLE_MISSING.value, "code": code})
    return hits


def scan_all():
    """扫描 repo 下所有 .py（跳过 gitignored 目录）。"""
    # gitignored 顶级目录（.git/.venv/.omo/build/dist/data）内的 .py 是第三方代码
    # 或本地产物，不属于项目源代码——跳过它们，否则基线被 vendor 代码污染，
    # --check 在换机器/CI 时会因 .venv 内容不同产生虚假新增违规。
    SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".omo", "build", "dist", "data"}
    all_hits = []
    for root, _dirs, files in os.walk(REPO):
        if any(seg in SKIP_DIRS for seg in root.split(os.sep)):
            continue
        for fn in files:
            if fn.endswith(".py"):
                all_hits += audit_file(os.path.join(root, fn))
    return all_hits


def write_baseline(hits):
    bl = os.path.join(REPO, "scripts", "styles_audit_baseline.json")
    # 按 (file, line, rule) 去重
    seen, out = set(), []
    for h in sorted(hits, key=lambda x: (x["file"], x["line"], x["rule"])):
        k = (h["file"], h["line"], h["rule"])
        if k not in seen:
            seen.add(k)
            out.append(h)
    with open(bl, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return bl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    hits = scan_all()
    if args.init:
        bl = write_baseline(hits)
        print(f"[audit] baseline written: {len(hits)} violations -> {bl}")
        return 0
    bl = os.path.join(REPO, "scripts", "styles_audit_baseline.json")
    if not os.path.exists(bl):
        print("[audit] no baseline; run --init first", file=sys.stderr)
        return 2
    baseline = {(h["file"], h["line"], h["rule"]) for h in json.load(open(bl, encoding="utf-8"))}
    new_hits = [h for h in hits if (h["file"], h["line"], h["rule"]) not in baseline]
    if args.report:
        for h in hits:
            print(f"{h['file']}:{h['line']} [{h['rule']}] {h['code']}")
        print(f"[audit] total={len(hits)} baseline={len(baseline)} new={len(new_hits)}")
    if new_hits:
        print(f"[audit] FAIL: {len(new_hits)} NEW violations (baseline {len(baseline)})")
        for h in new_hits[:30]:
            print(f"  NEW {h['file']}:{h['line']} [{h['rule']}] {h['code']}")
        return 1
    print(f"[audit] OK: {len(hits)} violations, none new vs baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())