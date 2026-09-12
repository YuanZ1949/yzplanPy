"""GUI 样式静态审计：扫描五类违规，输出基线并 diff（新增违规即 fail）。

用法：
  python scripts/audit_styles.py --init    全仓扫描，写入 styles_audit_baseline.json
  python scripts/audit_styles.py --check   对比基线，新增违规 exit 1（CI/pre-commit）
  python scripts/audit_styles.py --report  打印全部违规

五类规则：
  fixed_size        setFixedHeight/setMinimumHeight 魔法数字
  hex_color         QSS 字符串中的 #hex 硬编码颜色
  private_palette   模块内 def _xxx_colors() 私有调色板
  hardcoded_qss     模板内 setStyleSheet 拼接 hex/rgba 字面量
  size_literal      QSS 内数字 px 尺寸字面量（padding/width/height 等）
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
    PRIVATE_PALETTE = "private_palette"
    HARDCODED_QSS = "hardcoded_qss"
    SIZE_LITERAL = "size_literal"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 唯一允许裸 hex / 固定尺寸的代码区（阶段 3 前 qss 全局文件也豁免）
WHITELIST = {
    "core/theme/tokens.py",
    "core/theme/qss_dark.py",
    "core/theme/qss_light.py",
    "ui/widgets.py",
    "scripts/audit_styles.py",
    # perf_monitor._theme_colors 在 Task 7 后变为全局色板适配器（保留 perf
    # 专属图色扩展），不再自创基准色——豁免 private_palette；阶段 3 迁移
    # perf 时删除 _theme_colors 后移除本行。
    "modules/perf_monitor/styles.py",
}

RE_FIXED = re.compile(r"set(?:Fixed|Minimum)Height\(\s*(\d+)\s*\)")
RE_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
RE_PALETTE = re.compile(r"^\s*def\s+_(?:[a-z_]+_)?colors?\s*\(", re.M)
RE_QSS_HEX = re.compile(r'setStyleSheet\(\s*["\'].*?#[0-9a-fA-F]{6}', re.S)
# QSS 内数字 px 尺寸字面量（padding/width/height/border-radius/font-size 等）
RE_SIZE_LITERAL = re.compile(r"(?:padding|margin|width|height|border-radius|font-size|line-height):\s*\d+px", re.I)


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
        if RE_FIXED.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.FIXED_SIZE.value, "code": line.strip()})
        if RE_HEX.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.HEX_COLOR.value, "code": line.strip()})
        if RE_SIZE_LITERAL.search(line):
            hits.append({"file": rel, "line": i, "rule": Rule.SIZE_LITERAL.value, "code": line.strip()})
    for m in RE_PALETTE.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        hits.append({"file": rel, "line": ln, "rule": Rule.PRIVATE_PALETTE.value, "code": m.group(0).strip()})
    for m in RE_QSS_HEX.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        hits.append({"file": rel, "line": ln, "rule": Rule.HARDCODED_QSS.value, "code": lines[ln - 1].strip()})
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