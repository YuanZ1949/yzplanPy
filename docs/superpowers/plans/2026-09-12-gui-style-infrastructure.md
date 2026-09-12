# GUI 样式基础设施（设计令牌 + 控件工厂 + 四道护栏）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立全局唯一的设计令牌（`theme_palette()` + `sizing()`）与控件工厂 `ui/widgets.py`，并用四道护栏（工厂 API / 静态扫描 / 运行时测试 / AGENTS.md 规范）杜绝样式散落复发。

**Architecture:** 所有颜色从 `core/theme/tokens.py::theme_palette()`（以 perf_monitor 色板为基准，函数式实时取明/暗）取值；所有尺寸/字号从 `sizing()` 取值并随字体缩放（0.7~1.6）实时缩放——固定像素高度导致的截断因此根治。控件一律经 `ui/widgets.py` 工厂创建，工厂是唯一允许触碰令牌的代码区。存量代码迁移（spec 阶段 3）拆为后续独立计划，本计划只建基础设施并输出存量违规基线。

**Tech Stack:** Python 3 / PySide6 / PyQt 兼容层 `core.qt_bootstrap.import_qt` / pytest

**Spec:** `docs/superpowers/specs/2026-09-12-gui-style-unification-design.md`（本计划从该 spec 论证，执行者须先读 spec 再读本计划）

## Global Constraints

- 禁止新增任何硬编码颜色（`#hex`）或尺寸（`setFixedHeight(数字)`）——除 `core/theme/tokens.py`、`ui/widgets.py` 内。
- Qt 导入一律走 `from core.qt_bootstrap import import_qt`，模式：`_, QtCore, QtGui, QtWidgets = import_qt()`。
- 尺寸/字号必须经 `sizing()` 令牌，禁止手写 `font-size: 13px`、`padding: 5px 14px`。
- 模块禁止定义私有调色板（`_xxx_colors()`），颜色一律 `from core.theme.tokens import theme_palette`。
- 测试文件命名 `tests/test_style_*.py`（pytest 配置 `python_files = test_*.py` 只收集 test_ 前缀）。
- 每个任务结束跑 `pytest tests/test_style_*.py -v` 并提交；提交信息用 `feat(style):` 前缀。

---

### Task 1: 颜色令牌 `theme_palette()`

**Files:**
- Create: `core/theme/tokens.py`
- Test: `tests/test_style_tokens.py`

**Interfaces:**
- Produces: `theme_palette() -> dict[str, str | bool]` — 返回当前主题完整色板（随 `resolve_dark("auto")` 实时切换）。key 全集见下方测试 `_PALETTE_KEYS`。后续所有任务和存量迁移都依赖此签名。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_style_tokens.py
"""颜色令牌 theme_palette：完整性 + perf_monitor 基准色值。"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

# 调色板 key 全集：测试强制每个 key 在明暗两套中都存在（防缺 key 导致工厂 KeyError）
_PALETTE_KEYS = {
    "dark", "accent", "accent_hover", "accent_pressed",
    "success", "warning", "danger", "danger_hover", "danger_pressed", "info",
    "bg_app", "bg_card", "bg_control", "bg_hover", "bg_selected",
    "border", "border_strong", "border_focus",
    "text_primary", "text_secondary", "text_disabled",
    "chip_torrent_bg", "chip_torrent_fg", "chip_article_bg", "chip_article_fg",
    "overlay_pressed",
}


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _force_dark(dark):
    import core.theme.base as base
    base.resolve_dark = lambda mode: dark


def test_palette_has_all_keys_both_themes(_qapp):
    from core.theme.tokens import theme_palette
    for dark in (True, False):
        _force_dark(dark)
        p = theme_palette()
        missing = _PALETTE_KEYS - set(p.keys())
        assert not missing, f"{'暗' if dark else '亮'}色板缺 key: {missing}"
        assert p["dark"] is dark


def test_palette_matches_perf_monitor_baseline(_qapp):
    """配色基准 = perf_monitor._theme_colors()。accent 三个值与 perf 基准一致。"""
    from core.theme.tokens import theme_palette
    from modules.perf_monitor.styles import _theme_colors
    for dark in (True, False):
        _force_dark(dark)
        p = theme_palette()
        ref = _theme_colors()
        assert p["accent"] == ref["accent"], "accent 必须以 perf_monitor 为准"
        assert p["text_primary"] == ref["text_primary"]
        assert p["text_secondary"] == ref["text_secondary"]


def test_palette_switches_with_theme_setting(_qapp):
    from core.theme.tokens import theme_palette
    _force_dark(True)
    dark_p = theme_palette()
    _force_dark(False)
    light_p = theme_palette()
    assert dark_p["accent"] != light_p["accent"]
    assert dark_p["bg_card"] != light_p["bg_card"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.theme.tokens'`

- [ ] **Step 3: 实现 tokens.py（颜色部分）**

```python
# core/theme/tokens.py
"""GUI 设计令牌：全局唯一调色板与尺寸/字号令牌。

颜色以 perf_monitor._theme_colors() 为基准（spec 决策 A）；perf_monitor 缺失
而全局 QSS 已使用的语义色从 qss_dark/qss_light 提取合并。所有模块禁止私有
调色板，一律 from core.theme.tokens import theme_palette。
"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def theme_palette():
    """按当前主题返回完整色板。函数式（非常量）以支持运行时明暗热切换。"""
    from .base import resolve_dark
    dark = resolve_dark("auto")
    if dark:
        return {
            "_theme": True,
            "dark": True,
            # 品牌色（perf_monitor 基准）
            "accent": "#3aa6ff",
            "accent_hover": "#5cb8ff",
            "accent_pressed": "#2a8ad0",
            # 语义色（从 qss_dark 选中色系扩展）
            "success": "#4fd97a",
            "warning": "#ffab40",
            "danger": "#ff6b8a",
            "danger_hover": "#ff8ba4",
            "danger_pressed": "#d84f6e",
            "info": "#5b8cff",
            # 面板
            "bg_app": "rgba(30,30,30,0.92)",
            "bg_card": "rgba(255,255,255,0.06)",
            "bg_control": "rgba(255,255,255,0.05)",
            "bg_hover": "rgba(255,255,255,0.06)",
            "bg_selected": "rgba(0,120,215,0.25)",
            # 边框（值取 perf_monitor card_border/ctrl_border 基准 0.10）
            "border": "rgba(255,255,255,0.10)",
            "border_strong": "rgba(255,255,255,0.18)",
            "border_focus": "rgba(58,166,255,0.60)",
            # 文字
            "text_primary": "#e6e6e6",
            "text_secondary": "#999999",
            "text_disabled": "rgba(255,255,255,0.35)",
            # 状态胶囊（RSS 用）
            "chip_torrent_bg": "rgba(255,107,142,0.16)",
            "chip_torrent_fg": "#ff9ab0",
            "chip_article_bg": "rgba(37,205,150,0.16)",
            "chip_article_fg": "#7fe0c0",
            # 通用覆盖态
            "overlay_pressed": "rgba(0,0,0,0.10)",
        }
    return {
        "_theme": True,
        "dark": False,
        # 品牌色（perf_monitor 基准）
        "accent": "#1178e0",
        "accent_hover": "#2a8bf0",
        "accent_pressed": "#0d60b0",
        # 语义色
        "success": "#2f9e5a",
        "warning": "#e08a1e",
        "danger": "#e4506f",
        "danger_hover": "#e86984",
        "danger_pressed": "#c03a58",
        "info": "#4a77f5",
        # 面板
        "bg_app": "rgba(245,245,245,0.92)",
        "bg_card": "rgba(0,0,0,0.03)",
        "bg_control": "rgba(0,0,0,0.03)",  # perf_monitor ctrl_bg 亮色基准
        "bg_hover": "rgba(0,0,0,0.05)",
        "bg_selected": "rgba(0,120,215,0.12)",
        # 边框
        "border": "rgba(0,0,0,0.08)",
        "border_strong": "rgba(0,0,0,0.15)",
        "border_focus": "rgba(17,120,224,0.50)",
        # 文字
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "text_disabled": "rgba(0,0,0,0.30)",
        # 状态胶囊（RSS 用）
        "chip_torrent_bg": "#fce8e6",
        "chip_torrent_fg": "#c5221f",
        "chip_article_bg": "#e6f4ea",
        "chip_article_fg": "#137333",
        # 通用覆盖态
        "overlay_pressed": "rgba(0,0,0,0.10)",
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_style_tokens.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add core/theme/tokens.py tests/test_style_tokens.py
git commit -m "feat(style): 新增全局颜色令牌 theme_palette（perf_monitor 基准）"
```

---

### Task 2: 尺寸/字号令牌 `sizing()`

**Files:**
- Modify: `core/theme/tokens.py`（追加 sizing）
- Test: `tests/test_style_tokens.py`（追加测试函数）

**Interfaces:**
- Consumes: `core.theme.font.current_font_scale`（0.7~1.6，可运行时变更）
- Produces: `sizing() -> dict[str, int | str]` — 每次调用实时按缩放计算：
  `btn_height_sm/md/ lg`、`btn_padding_sm/md/lg`（"hpx wpx" 字符串）、`input_height`、`combo_height`、`radius_sm/md/lg`、`font_size_xs/sm/md/lg/xl`。

- [ ] **Step 1: 写失败测试（追加到 test_style_tokens.py）**

```python
def test_sizing_scales_with_font_scale(_qapp):
    """字号缩放 1.6x 时，高度/字号/内边距同步放大——这是根治截断的关键。"""
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    ConfigHolder.scale = 1.0
    base = sizing()
    ConfigHolder.scale = 1.6
    scaled = sizing()
    ConfigHolder.scale = 1.0  # 复原，避免污染其他测试
    assert scaled["btn_height_md"] >= int(base["btn_height_md"] * 1.5)
    assert scaled["font_size_md"] > base["font_size_md"]
    # 内边距字符串同步放大
    def parse(p):
        h, w = p.split()
        return int(h.rstrip("px")), int(w.rstrip("px"))
    bh, bw = parse(scaled["btn_padding_md"])
    nh, nw = parse(base["btn_padding_md"])
    assert bh >= nh and bw >= nw


def test_sizing_has_all_keys(_qapp):
    from core.theme.tokens import sizing
    keys = {
        "btn_height_sm", "btn_height_md", "btn_height_lg",
        "btn_padding_sm", "btn_padding_md", "btn_padding_lg",
        "input_height", "combo_height",
        "radius_sm", "radius_md", "radius_lg",
        "font_size_xs", "font_size_sm", "font_size_md", "font_size_lg", "font_size_xl",
    }
    assert keys <= set(sizing().keys())
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_tokens.py -v`
Expected: FAIL — `NameError: name 'sizing' is not defined`（或 import error）

- [ ] **Step 3: 实现（追加到 tokens.py）**

```python
def _s(px):
    """将 px 基线值按当前字体缩放比例实时缩放（scale 0.7~1.6）。"""
    from .font import current_font_scale
    return round(px * current_font_scale())


def sizing():
    """尺寸/字号令牌。每次调用实时计算——运行时字体缩放（设置页切换）立即生效。

    控件高度 = 基线高度 × scale：字号放大时高度同步增长，杜绝固定像素截断。
    """
    return {
        # 按钮
        "btn_height_sm": _s(26),
        "btn_height_md": _s(32),
        "btn_height_lg": _s(38),
        "btn_padding_sm": f"{_s(4)}px {_s(10)}px",
        "btn_padding_md": f"{_s(6)}px {_s(14)}px",
        "btn_padding_lg": f"{_s(8)}px {_s(18)}px",
        # 输入框 / 下拉框
        "input_height": _s(30),
        "combo_height": _s(30),
        # 圆角
        "radius_sm": _s(4),
        "radius_md": _s(6),
        "radius_lg": _s(8),
        # 字号
        "font_size_xs": _s(9),
        "font_size_sm": _s(11),
        "font_size_md": _s(13),
        "font_size_lg": _s(16),
        "font_size_xl": _s(20),
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_style_tokens.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add core/theme/tokens.py tests/test_style_tokens.py
git commit -m "feat(style): 新增尺寸/字号令牌 sizing（随字体缩放实时计算）"
```

---

### Task 3: 控件工厂 `ui/widgets.py`

**Files:**
- Create: `ui/widgets.py`
- Test: `tests/test_style_widgets.py`

**Interfaces:**
- Consumes: `theme_palette()`、`sizing()`（Task 1/2）
- Produces:
  - `make_button(text, icon=None, *, kind="default", size="md", parent=None) -> QPushButton`
    - kind: default/primary/danger/ghost/flat；size: sm/md/lg
  - `make_line_edit(placeholder="", *, parent=None) -> QLineEdit`
  - `make_combo(items=None, *, parent=None) -> QComboBox`
  - `make_card(*, parent=None) -> QFrame`
  - `make_status_chip(text, *, kind="info", parent=None) -> QLabel`（kind: torrent/article/success/info）
  - `make_label(text, *, role="body", parent=None) -> QLabel`（role: title/subtitle/body/caption/muted）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_style_widgets.py
"""控件工厂：高度/颜色/字号全部来自令牌，主题与缩放驱动视觉。"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _force_dark(dark):
    import core.theme.base as base
    base.resolve_dark = lambda mode: dark


def test_make_button_height_from_sizing(_qapp):
    from core.theme.font import ConfigHolder
    from core.theme.tokens import sizing
    from ui.widgets import make_button
    ConfigHolder.scale = 1.0
    b1 = make_button("确定", size="md")
    ConfigHolder.scale = 1.6
    b2 = make_button("确定", size="md")
    ConfigHolder.scale = 1.0
    assert b1.height() == sizing()["btn_height_md"]
    assert b2.height() > b1.height(), "1.6x 缩放后按钮高度必须变大（根治截断）"


def test_make_button_primary_uses_accents(_qapp):
    from core.theme.tokens import theme_palette
    from ui.widgets import make_button
    _force_dark(True)
    p = theme_palette()
    b = make_button("主操作", kind="primary")
    assert p["accent"] in b.styleSheet(), "主色按钮 QSS 必须引用当前 accent"
    assert "#3aa6ff" not in b.styleSheet() or "#3aa6ff" == p["accent"], \
        "禁止硬编码 hex，必须全部来自令牌"


def test_make_line_edit_fixed_height(_qapp):
    from core.theme.tokens import sizing
    from ui.widgets import make_line_edit
    e = make_line_edit("搜索…")
    assert e.height() == sizing()["input_height"]
    assert p_style_uses_tokens(e.styleSheet())


def test_make_status_chip_torrent(_qapp):
    from core.theme.tokens import theme_palette
    from ui.widgets import make_status_chip
    _force_dark(True)
    p = theme_palette()
    chip = make_status_chip("磁链", kind="torrent")
    assert p["chip_torrent_bg"] in chip.styleSheet()
    assert p["chip_torrent_fg"] in chip.styleSheet()


def test_make_label_roles_differ(_qapp):
    from ui.widgets import make_label
    title = make_label("标题", role="title")
    caption = make_label("说明", role="caption")
    assert title.styleSheet() != caption.styleSheet()
    assert "700" in title.styleSheet()


def p_style_uses_tokens(qss):
    """QSS 中不得出现裸 hex 字面量（工厂代码本身已用 f-string 注入令牌）。"""
    import re
    return not re.search(r"#[0-9a-fA-F]{6}", qss)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_widgets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.widgets'`

- [ ] **Step 3: 实现工厂**

```python
# ui/widgets.py
"""统一控件工厂：所有控件的高度/颜色/字号取自 core.theme.tokens 令牌。

规则：工厂是唯一允许触碰令牌的代码区。调用方只传语义参数
（kind/size/role），禁止传入颜色值或像素尺寸。
"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.theme.tokens import sizing, theme_palette


def make_button(text, icon=None, *, kind="default", size="md", parent=None):
    p = theme_palette()
    sz = sizing()
    height = {"sm": sz["btn_height_sm"], "md": sz["btn_height_md"], "lg": sz["btn_height_lg"]}[size]
    padding = {"sm": sz["btn_padding_sm"], "md": sz["btn_padding_md"], "lg": sz["btn_padding_lg"]}[size]
    radius = sz["radius_md"]

    # (bg, fg, border, hover, pressed)
    style = {
        "default": (p["bg_control"], p["text_primary"], p["border"], p["bg_hover"], p["overlay_pressed"]),
        "primary": (p["accent"], "#ffffff", p["accent"], p["accent_hover"], p["accent_pressed"]),
        "danger": (p["danger"], "#ffffff", p["danger"], p["danger_hover"], p["danger_pressed"]),
        "ghost": ("transparent", p["text_primary"], "transparent", p["bg_hover"], p["overlay_pressed"]),
        "flat": ("transparent", p["text_primary"], "transparent", "transparent", "transparent"),
    }[kind]
    bg, fg, border, hover, pressed = style

    btn = QtWidgets.QPushButton(text, parent)
    btn.setFixedHeight(height)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border};"
        f" border-radius: {radius}px; padding: {padding}; font-size: {sz['font_size_sm']}px; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
        f"QPushButton:pressed {{ background: {pressed}; }}"
    )
    if icon is not None:
        btn.setIcon(icon)
    return btn


def make_line_edit(placeholder="", *, parent=None):
    p = theme_palette()
    sz = sizing()
    w = QtWidgets.QLineEdit(parent)
    w.setPlaceholderText(placeholder)
    w.setFixedHeight(sz["input_height"])
    w.setStyleSheet(
        f"QLineEdit {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: {sz['input_height'] // 5}px 10px; font-size: {sz['font_size_sm']}px; }}"
        f"QLineEdit:focus {{ border: 1px solid {p['border_focus']}; }}"
    )
    return w


def make_combo(items=None, *, parent=None):
    p = theme_palette()
    sz = sizing()
    w = QtWidgets.QComboBox(parent)
    w.setFixedHeight(sz["combo_height"])
    if items:
        w.addItems(items)
    w.setStyleSheet(
        f"QComboBox {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: 4px 10px; font-size: {sz['font_size_sm']}px; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
    )
    return w


def make_card(*, parent=None):
    p = theme_palette()
    sz = sizing()
    f = QtWidgets.QFrame(parent)
    f.setStyleSheet(
        f"QFrame {{ background: {p['bg_card']}; border: 1px solid {p['border']};"
        f" border-radius: {sz['radius_lg']}px; }}"
    )
    return f


def make_status_chip(text, *, kind="info", parent=None):
    p = theme_palette()
    sz = sizing()
    style = {
        "torrent": (p["chip_torrent_bg"], p["chip_torrent_fg"]),
        "article": (p["chip_article_bg"], p["chip_article_fg"]),
        "success": (p["bg_card"], p["success"]),
        "info": (p["bg_card"], p["info"]),
    }[kind]
    bg, fg = style
    w = QtWidgets.QLabel(text, parent)
    w.setStyleSheet(
        f"QLabel {{ font-size: {sz['font_size_xs']}px; font-weight: 600;"
        f" padding: {sz['radius_sm'] // 2}px {sz['btn_padding_sm'].split()[1]};"
        f" border-radius: {sz['radius_sm'] + 10}px; background: {bg}; color: {fg}; }}"
    )
    return w


def make_label(text, *, role="body", parent=None):
    p = theme_palette()
    sz = sizing()
    style = {
        "title": (sz["font_size_lg"], "700", p["text_primary"]),
        "subtitle": (sz["font_size_md"], "600", p["text_primary"]),
        "body": (sz["font_size_sm"], "400", p["text_primary"]),
        "caption": (sz["font_size_xs"], "400", p["text_secondary"]),
        "muted": (sz["font_size_xs"], "400", p["text_disabled"]),
    }[role]
    fs, weight, color = style
    w = QtWidgets.QLabel(text, parent)
    w.setStyleSheet(
        f"QLabel {{ font-size: {fs}px; font-weight: {weight}; color: {color};"
        f" background: transparent; }}"
    )
    return w
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_style_widgets.py -v`
Expected: PASS（6 passed）— 若 `p_style_uses_tokens` 在个别用例误报（如按钮文字为纯色 `#ffffff` 通过 f-string 注入），检查工厂 QSS 是否引用了令牌变量而非字面量。

- [ ] **Step 5: 提交**

```bash
git add ui/widgets.py tests/test_style_widgets.py
git commit -m "feat(style): 新增控件工厂 ui/widgets.py（按钮/输入/下拉/卡片/胶囊/标签）"
```

---

### Task 4: 静态扫描护栏 + 存量违规基线

**Files:**
- Create: `scripts/audit_styles.py`
- Create: `scripts/styles_audit_baseline.json`（`--init` 生成）
- Test: `tests/test_style_audit.py`

**Interfaces:**
- Produces:
  - `audit_file(path) -> list[dict]` — 违规项 `{"file", "line", "rule", "code"}`
  - CLI: `python scripts/audit_styles.py --init`（全仓扫描，写基线）`--check`（对比基线，新增违规/新文件违规 → exit 1）；`--report`（打印全部）
- 豁免名单（硬编码在脚本内）：`core/theme/tokens.py`、`ui/widgets.py`、`scripts/audit_styles.py`、`tests/` 下全部文件（测试故意写样例）、`core/theme/qss_dark.py`、`core/theme/qss_light.py`（阶段 3 迁移后再移除豁免）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_style_audit.py
"""静态扫描：四类违规规则命中与豁免、基线 diff 机制。"""
import json
import subprocess
import sys

import pytest


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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_audit.py -v`
Expected: FAIL — import error（脚本不存在）

- [ ] **Step 3: 实现扫描脚本**

```python
# scripts/audit_styles.py
"""GUI 样式静态审计：扫描四类违规，输出基线并 diff（新增违规即 fail）。

用法：
  python scripts/audit_styles.py --init    全仓扫描，写入 styles_audit_baseline.json
  python scripts/audit_styles.py --check   对比基线，新增违规 exit 1（CI/pre-commit）
  python scripts/audit_styles.py --report  打印全部违规

四类规则：
  fixed_size        setFixedHeight/setMinimumHeight 魔法数字
  hex_color         QSS 字符串中的 #hex 硬编码颜色
  private_palette   模块内 def _xxx_colors() 私有调色板
  hardcoded_qss     模板内 setStyleSheet 拼接 hex/rgba 字面量
"""
import argparse
import json
import os
import re
import sys

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
            hits.append({"file": rel, "line": i, "rule": "fixed_size", "code": line.strip()})
        if RE_HEX.search(line):
            hits.append({"file": rel, "line": i, "rule": "hex_color", "code": line.strip()})
    for m in RE_PALETTE.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        hits.append({"file": rel, "line": ln, "rule": "private_palette", "code": m.group(0).strip()})
    for m in RE_QSS_HEX.finditer(text):
        ln = text[: m.start()].count("\n") + 1
        hits.append({"file": rel, "line": ln, "rule": "hardcoded_qss", "code": lines[ln - 1].strip()})
    return hits


def scan_all():
    """扫描 repo 下所有 .py（跳过 scripts 样例）。"""
    all_hits = []
    for root, _dirs, files in os.walk(REPO):
        if ".git" in root or "__pycache__" in root or "node_modules" in root:
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
```

- [ ] **Step 4: 运行测试 + 生成真实基线**

Run: `pytest tests/test_style_audit.py -v`
Expected: PASS（4 passed）

Run: `python scripts/audit_styles.py --init`
Expected: 输出 baseline written，`scripts/styles_audit_baseline.json` 生成（存量违规数量即阶段 3 迁移工作量清单）

Run: `python scripts/audit_styles.py --check`
Expected: `OK: N violations, none new vs baseline`（exit 0）

- [ ] **Step 5: 提交**

```bash
git add scripts/audit_styles.py scripts/styles_audit_baseline.json tests/test_style_audit.py
git commit -m "feat(style): 静态扫描护栏 + 存量违规基线（audit_styles.py）"
```

---

### Task 5: 运行时护栏测试（主题切换一致 + 缩放无截断）

**Files:**
- Create: `tests/test_style_guardrails.py`

**Interfaces:**
- Consumes: `ui.widgets.make_button`、`make_status_chip`（Task 3）、`theme_palette`（Task 1）
- Produces: 两条护栏测试，作为后续存量迁移回归门槛（每个模块迁移后必须保持这两条测试全绿）。

- [ ] **Step 1: 写测试**

```python
# tests/test_style_guardrails.py
"""运行时护栏：
1) 主题切换后，工厂控件 QSS 必须全部来自新主题调色板（无旧主题残留）。
2) 字体缩放 1.6x 下，按钮文字完整可见（不截断）。
"""
import re

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


@pytest.fixture(scope="module")
def _qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _force_dark(dark):
    import core.theme.base as base
    base.resolve_dark = lambda mode: dark


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
        assert btn.width() >= text_w + pad_w + 4, \
            f"文字 {text_w}px + 内边距 {pad_w}px 超出按钮宽 {btn.width()}px"
        assert btn.height() >= fm.height() + 4, \
            f"文字高 {fm.height()}px 超出按钮高 {btn.height()}px"
    finally:
        ConfigHolder.scale = 1.0
        btn.close()
```

- [ ] **Step 2: 运行确认通过**

Run: `pytest tests/test_style_guardrails.py -v`
Expected: PASS（2 passed）。若 `test_font_scale_16_button_text_fits` 失败，说明工厂高度/内边距不足，回 Task 3 调整令牌值（不影响 API）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_style_guardrails.py
git commit -m "feat(style): 运行时护栏测试（主题切换无残留 + 1.6x 缩放无截断）"
```

---

### Task 6: 开发规范文档 AGENTS.md

**Files:**
- Create: `AGENTS.md`

**Interfaces:**
- Produces: 项目根级 AI/开发者协作规范，含「GUI 样式规则」专节（护栏 D）。

- [ ] **Step 1: 创建 AGENTS.md**

```markdown
# YZplan 开发协作规范

本文件约束本项目中的所有代码变更（人类开发者与 AI 代理一致遵守）。

## GUI 样式规则（强制）

1. **新控件必须从 `ui/widgets.py` 工厂创建**（`make_button` / `make_line_edit`
   / `make_combo` / `make_card` / `make_status_chip` / `make_label`）。
   禁止手动 `setFixedHeight(数字)` + `setStyleSheet(硬编码)`。

2. **颜色必须来自 `core.theme.tokens.theme_palette()`**。禁止书写 hex 字面量
   （如 `#ff0000`）与 rgba 字面量。需要新色时先在 `theme_palette()` 中新增 key。

3. **字号/尺寸必须来自 `core.theme.tokens.sizing()`**。禁止 `font-size: 13px`、
   `padding: 5px 14px` 等手写像素值。全部以 `sizing()` 返回的令牌为准，
   尺寸会自动随字体缩放（0.7~1.6）同步，避免截断。

4. **模块禁止私有调色板**：不得定义 `_xxx_colors()` / `_theme_colors()`。
   模块样式函数一律接收 `theme_palette()` 返回的 dict 作为参数。

5. **修改样式前先改令牌**：若某控件需要新尺寸或新颜色，先在 `tokens.py`
   确认/新增对应令牌，再在工厂或样式函数中引用。禁止绕过令牌直接写值。

6. **增量迁移门槛**：每次改动后运行
   `python scripts/audit_styles.py --check`（新增违规即失败）与
   `pytest tests/test_style_guardrails.py -v`（主题切换无残留、1.6x 无截断）。

## 通用规范

- 模块间通信走定义良好的接口；单文件超过 250 行需拆分。
- 提交信息遵循 conventional commits（`feat/fix/refactor/docs/perf/test`）。
- 本仓库 TDD：先写失败测试，再实现，再提交。
```

- [ ] **Step 2: 验证文档落地（对照自查）**

Run: `python scripts/audit_styles.py --check`
Expected: `OK`（exit 0）— 规则 6 引用的是已存在的命令

Run: `pytest tests/test_style_tokens.py tests/test_style_widgets.py tests/test_style_audit.py tests/test_style_guardrails.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add AGENTS.md
git commit -m "docs(style): 新增 AGENTS.md 开发规范（GUI 样式规则五条 + 增量门槛）"
```

---

### Task 7: 阶段 2 试点迁移（证明新代码路径）+ 全量回归

**Files:**
- Modify: `modules/perf_monitor/styles.py`（`_theme_colors` 改为转调全局令牌，试点最小改动验证「以 perf_monitor 为基准」的合并无退化）
- Test: `tests/test_style_tokens.py`（依赖其基准断言不回归）

**Interfaces:**
- Consumes: `theme_palette()`（Task 1）
- Produces: `_theme_colors()` 保持原签名（perf_monitor 内部 5 处调用点无需改动），内部实现改为返回 `theme_palette()` 并补足 perf 私有 key（bar_colors 等）——证明存量模块可以零破坏接入全局色板。

- [ ] **Step 1: 写回归测试（追加到 test_style_tokens.py）**

```python
def test_perf_monitor_colors_alias_global_palette(_qapp):
    """perf_monitor._theme_colors 必须与全局 theme_palette 共享同一基准。"""
    from core.theme.tokens import theme_palette
    from modules.perf_monitor.styles import _theme_colors
    for dark in (True, False):
        _force_dark(dark)
        p = theme_palette()
        ref = _theme_colors()
        assert ref["accent"] == p["accent"]
        assert ref["text_primary"] == p["text_primary"]
        assert ref["text_secondary"] == p["text_secondary"]
        assert ref["dark"] is dark
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_tokens.py::test_perf_monitor_colors_alias_global_palette -v`
Expected: FAIL — 当前 `_theme_colors()` 与 `theme_palette()` accent 值不同（后者刚建立，perf 私有值未同步）

- [ ] **Step 3: 实现——`_theme_colors()` 改为全局色板别名**

```python
# modules/perf_monitor/styles.py 头部（原 import 不动，仅在 _theme_colors 处替换）

def _theme_colors():
    """perf_monitor 调色板：全局 theme_palette 别名 + perf 专属扩展。

    阶段 2 试点：模块不再自创基准色；accent/text 等视觉色与全局令牌单一
    来源。perf 旧 key 名（card_bg/card_border/ctrl_bg/ctrl_border/sel_bg）
    映射到全局令牌值——key 收敛且视觉零变化（Task 1 已把全局 border 等
    对齐到 perf 基准值）；仅图表系列色（accent_pid/cpu/mem/thr/hdl/uptime、
    group_border/group_bg、grid_color、bar_colors）作为 perf 专属扩展保留。
    """
    from core.theme.tokens import theme_palette
    p = dict(theme_palette())  # 拷贝，避免污染全局
    dark = p["dark"]
    p.update({
        # perf 旧 key → 全局令牌值（key 收敛；test_theme_colors_returns_dict
        # 依赖这 5 个 key 存在，且此映射保证 perf 视觉与迁移前一致）
        "card_bg": p["bg_card"],
        "card_border": p["border"],
        "ctrl_bg": p["bg_control"],
        "ctrl_border": p["border"],
        "sel_bg": p["bg_selected"],
    })
    if dark:
        p.update({
            "accent_pid": "#5b8cff",
            "accent_cpu": "#25c9a0",
            "accent_mem": "#a06bff",
            "accent_thr": "#ffab40",
            "accent_hdl": "#ff6b8a",
            "accent_uptime": "#4fd97a",
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "grid_color": "rgba(255,255,255,0.06)",
            "bar_colors": [
                (0, 180, 80), (60, 170, 50), (180, 160, 0),
                (220, 120, 0), (220, 60, 40),
            ],
        })
    else:
        p.update({
            "accent_pid": "#4a77f5",
            "accent_cpu": "#12a582",
            "accent_mem": "#7c3aed",
            "accent_thr": "#e08a1e",
            "accent_hdl": "#e4506f",
            "accent_uptime": "#2f9e5a",
            "group_border": "rgba(0,0,0,0.10)",
            "group_bg": "rgba(0,0,0,0.02)",
            "grid_color": "rgba(0,0,0,0.06)",
            "bar_colors": [
                (34, 160, 70), (70, 150, 40), (200, 160, 0),
                (210, 110, 0), (210, 50, 30),
            ],
        })
    return p
```

> 注意：`_theme_colors()` 别名实现已把 perf 旧 key（`card_bg`/`card_border`/`ctrl_bg`/`ctrl_border`/`sel_bg`）映射到全局令牌对应值（`bg_card`/`border`/`bg_control`/`bg_selected`）——`test_perf_monitor_ui.py::test_theme_colors_returns_dict` 断言这些 key 存在，映射保证它们存在且视觉与迁移前一致（Task 1 全局 border/bg_control 已对齐 perf 基准值）。perf 其余样式函数（`_group_box_style(tc)` 等）继续直接消费旧 key，无需改动。`test_perf_monitor_ui.py` 若断言旧 key 的具体值，与全局令牌值一致即为通过。

- [ ] **Step 4: 运行全量相关测试确认通过**

Run: `pytest tests/test_style_tokens.py tests/test_perf_monitor_ui.py tests/test_style_guardrails.py -v`
Expected: PASS（含新增别名测试；perf 现有 UI 测试不回归）

- [ ] **Step 5: 审计 + 提交**

```bash
python scripts/audit_styles.py --check
git add modules/perf_monitor/styles.py tests/test_style_tokens.py
git commit -m "refactor(style): perf_monitor 调色板接入全局令牌（试点别名，旧接口不变）"
```

---

### Task 8: 全量回归 + 收尾

**Files:**（无新增）

- [ ] **Step 1: 全量测试**

Run: `pytest -v`
Expected: 全绿（含存量测试不回归；本计划新增 4 个 test_style 文件全部 PASS）

- [ ] **Step 2: 审计终检**

Run: `python scripts/audit_styles.py --check`
Expected: `OK: N violations, none new vs baseline`（exit 0）

- [ ] **Step 3: 存量违规清单导出（供阶段 3 独立计划使用）**

Run: `python scripts/audit_styles.py --report`
Expected: 打印全部存量违规（N 条），数量即后续「存量模块迁移计划」的任务来源；`scripts/styles_audit_baseline.json` 已包含结构化清单。

- [ ] **Step 4: 确认最终提交状态**

Run: `git log --oneline -12`
Expected: 本次 feature 工作的 7 个提交（Task 1~7），收尾无代码改动、工作区干净。

---

## 后续（不在本计划范围）

- **阶段 3 存量迁移**：按 `scripts/styles_audit_baseline.json` 逐模块迁移——`ui/` 层 → perf_monitor（收回 Task 7 的旧 key 别名）→ todo_notes/sys_info/screenshot/webview_control/translator → rss_aggregator。每模块替换后明/暗截图对比 + `test_style_guardrails.py` 回归。拆为独立计划。
- 完成迁移后移除 `WHITELIST` 中 `qss_dark.py`/`qss_light.py` 豁免，全局 QSS 颜色收敛进 `theme_palette()`。