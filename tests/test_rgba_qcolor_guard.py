"""C6① rgba→QColor 根因护栏（notes-backlog-dev todo 11）。

根因（已由 qcolor_check.py 实证）：Qt6 的 `QColor("rgba(...)")` 无效，
绘制为不透明黑；`core.theme.tokens.rgba_to_qcolor()` 返回有效 QColor。

两道护栏：
1) 明暗两套主题下，每个含 `rgba(` 的 theme_palette() 值都必须能被
   rgba_to_qcolor() 解析为有效 QColor（覆盖所有被 Python 绘制消费的 rgba 令牌）。
2) 本 todo 列出的 paint 站点模块中，不得出现「把 rgba 令牌值直接传给 QColor」
   的调用——每个 `QColor(` 要么是 hex 字面量/hex 令牌，要么被 rgba_to_qcolor()
   包裹（QSS 内的 rgba 字符串不受此约束，QSS 原生支持 rgba）。
"""
import ast
from pathlib import Path

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_REPO = Path(__file__).resolve().parents[1]

# todo 11 名单：本计划修复/审计的 paint 站点（禁止越界改动名单外模块）
_LISTED_MODULES = (
    "modules/win_maintenance/timeline_chart.py",
    "modules/perf_monitor/bar.py",
    "modules/todo_notes/delegate.py",
    "modules/win_maintenance/page.py",
    "modules/win_maintenance/agg_view.py",
    "modules/webview_control/page.py",
    "modules/todo_notes/date_theme.py",
)


def _rgba_palette_values():
    """产出 (主题名, key, value)：两套主题下所有含 rgba( 的字符串令牌值。"""
    from core.theme.tokens import theme_palette
    for dark in (True, False):
        p = theme_palette(dark=dark)
        for key, value in p.items():
            if isinstance(value, str) and "rgba(" in value:
                yield ("dark" if dark else "light"), key, value


def test_every_rgba_palette_value_parses_via_rgba_to_qcolor():
    """每个含 rgba( 的令牌值在明暗两套主题下都能被 rgba_to_qcolor 解析为有效 QColor。"""
    from core.theme.tokens import rgba_to_qcolor
    values = list(_rgba_palette_values())
    assert values, "测试前提：调色板必须至少有一个 rgba 令牌"
    for theme, key, value in values:
        c = rgba_to_qcolor(value)
        assert c.isValid(), f"{theme}.{key}={value} -> rgba_to_qcolor 无效"


def _qcolor_args(tree):
    """产出源码中每个 QColor(...) 调用的首个实参 AST 节点。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if name == "QColor" and node.args:
                yield node.args[0]


def _resolve_arg(arg, palette):
    """把 QColor 实参解析为调色板值字符串；无法静态判定返回 None。

    规则（todo 11 验收）：
    - rgba_to_qcolor(...) 包裹 → 合规（返回 None，无需检查）
    - 字符串字面量 → 返回该字面量（hex/命名色合规，rgba 字面量违规）
    - X["key"] 下标 → 返回 palette[key]
    - X.get("key", default) → 解析 default（覆盖 tc.get(key, 兜底) 模式）
    - 其余（变量/整型实参/其他调用）→ None（无法静态证明违规）
    """
    if isinstance(arg, ast.Call):
        fname = arg.func.attr if isinstance(arg.func, ast.Attribute) else (
            arg.func.id if isinstance(arg.func, ast.Name) else None)
        if fname == "rgba_to_qcolor":
            return None
        if fname == "get" and len(arg.args) >= 2:
            return _resolve_arg(arg.args[1], palette)
        return None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Subscript):
        sl = arg.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            return palette.get(sl.value)
    return None


def test_listed_modules_no_direct_qcolor_of_rgba_palette_value():
    """列出的模块不得把 rgba 令牌值直接传给 QColor（必须经 rgba_to_qcolor 或为 hex）。"""
    from core.theme.tokens import theme_palette
    palettes = (theme_palette(dark=True), theme_palette(dark=False))
    violations = []
    for rel in _LISTED_MODULES:
        src = (_REPO / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for arg in _qcolor_args(tree):
            for pal in palettes:
                val = _resolve_arg(arg, pal)
                if val is not None and "rgba(" in val:
                    violations.append(
                        f"{rel}: QColor({ast.unparse(arg)}) 直接使用 rgba 令牌 {val}")
                    break
    assert not violations, "发现直接 QColor(rgba 令牌) 调用：\n" + "\n".join(violations)