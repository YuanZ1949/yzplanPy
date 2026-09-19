# 四层方案：工厂补齐 + 视觉资产 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在品牌色体系（Mode 1/2/3，已完成）之后，补齐第 1 层（GUI 工厂能力）与第 3 层（Fluent 2 视觉资产：阴影/动效/圆角/窗口底色对齐），全部 TDD + 令牌化 + 门禁验证。

**Architecture:** 第 1 层只补两个真实缺口工厂 `make_checkbox` / `make_tool_button`（消灭 webview_control 与 todo_notes 的 QSS 直写点）；第 3 层在 `tokens.py` 增加阴影/动效/圆角令牌（sizing/theme_palette 白名单内），`ui/widgets.py` 提供 `attach_card_shadow` 封装，并对齐 Fluent-M3U8 窗口底色（32,32,32 / 240,244,249）。所有视觉变更走「黄金测试 + 截图对照 + audit 门禁」Wave 惯例。

**Tech Stack:** PySide6 + qfluentwidgets；token 体系 `core/theme/tokens.py`（theme_palette/sizing，audit 白名单）；工厂层 `ui/widgets.py`（唯一允许触碰令牌的代码区）；测试 pytest + offscreen、样式审计 `scripts/audit_styles.py --check`。

**Spec:** 用户 m0027 拍板 Mode 1+2+3 全量（已完成，commit bedb0d3）；当前规划接续四层方案的第 1 层与第 3 层。第 2 层（存量违规迁移）经体检 baseline=0，无违规可迁移，已完结。

## Global Constraints

- 执行器固定：`.venv\Scripts\python.exe` + `$env:QT_QPA_PLATFORM="offscreen"`，workdir=C:\MyFile\Desktop\yzplanPy。禁止用系统 anaconda python（Qt DLL 缺 ICU）。
- 新控件必须从 `ui/widgets.py` 工厂创建；禁止模块内 `setStyleSheet` 硬编码 hex/rgba 字面量；颜色必须来自 `theme_palette()`、尺寸来自 `sizing()`（含 `_s()` 缩放）。
- 模块禁止私有调色板（rss styles.py 现有函数经 `rss_style_vars()` 只取全局令牌，合规，保留）。
- 每次改动后跑 `python scripts/audit_styles.py --check`（新增违规 exit 1）与 `pytest tests/test_style_guardrails.py -v`。
- TDD：先写失败测试，再实现，再提交；提交遵循 conventional commits；单文件超 250 行需拆分。
- 新增测试文件必须登记进 `.github/workflows/python-app.yml` 的 4 个 chunk（显式枚举）。
- GUI 截图验证需先启动：`Start-Process .venv\Scripts\pythonw.exe main.py`；旧实例必须 Stop-Process 后再启（旧进程跑旧代码，截图会误导）。
- 批量 pytest 已知 0xC0000005 崩溃：`tests/test_todo_notes_ui.py` 与 `tests/test_perf_monitor_ui.py` 必须分进程单独跑，严禁同批混跑。
- Wave 惯例：改前截图 → 迁移 → 审计 + 守卫测试 → 改后截图 → 单 commit。

---

### Task 1: make_checkbox 工厂 + webview_control 封禁开关迁移

**Files:**
- Modify: `ui/widgets.py`（工厂末尾追加 make_checkbox）
- Modify: `modules/webview_control/page.py:384-386`（直写 QSS 迁移）
- Modify: `core/theme/tokens.py`（sizing() 新增 checkbox 令牌）
- Test: `tests/test_style_widgets.py`（追加用例）+ `tests/test_webview_merged.py`（现有即可，不新增文件）

**Interfaces:**
- Consumes: `theme_palette()`（text_primary/bg_card/border/accent/hover 等）、`sizing()`（font_size_sm/radius_sm/checkbox 新令牌）
- Produces: `make_checkbox(text="", *, parent=None) -> QtWidgets.QCheckBox`（令牌化 QSS，含 ::indicator checked 态 accent）；sizing() 新增 `checkbox_size=16`、`checkbox_spacing=6`

- [ ] **Step 1: 在 sizing() 增加令牌（先实现，这是白名单配置，无独立测试）**

在 `core/theme/tokens.py` sizing() dict 内（`_ed_pad` 附近）加：
```python
# 通用复选框（Task 1：工厂 make_checkbox 尺寸）
"checkbox_size": _s(16),
"checkbox_spacing": _s(6),
```

- [ ] **Step 2: 写失败测试**

在 `tests/test_style_widgets.py` 追加（该文件已登记 CI chunk3，无需新登记）：
```python
def test_make_checkbox_returns_checkbox(qapp):
    from ui.widgets import make_checkbox
    cb = make_checkbox("封禁")
    assert isinstance(cb, QtWidgets.QCheckBox)
    assert cb.text() == "封禁"
    assert cb.isChecked() is False

def test_make_checkbox_qss_uses_tokens_no_hardcode(qapp):
    from ui.widgets import make_checkbox
    from core.theme.tokens import sizing, theme_palette
    cb = make_checkbox("x")
    qss = cb.styleSheet()
    p = theme_palette(); sz = sizing()
    assert p["text_primary"] in qss          # 令牌引用
    assert f"{sz['checkbox_spacing']}px" in qss
    assert f"{sz['checkbox_size']}px" in qss
    # 禁止硬编码色
    import re
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", qss)
    assert "rgba(" not in qss

def test_make_checkbox_checked_uses_accent(qapp):
    from ui.widgets import make_checkbox
    from core.theme.tokens import theme_palette
    cb = make_checkbox("x"); cb.setChecked(True)
    qss = cb.styleSheet()
    assert theme_palette()["accent"] in qss  # ::indicator:checked 背景
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: FAIL——`ImportError: cannot import name 'make_checkbox' from 'ui.widgets'`

- [ ] **Step 4: 实现 make_checkbox**

在 `ui/widgets.py` make_label 之后追加：
```python
def make_checkbox(text="", *, parent=None):
    """令牌化复选框。::indicator 尺寸/间距来自 sizing()，checked 态用 accent。"""
    p = theme_palette()
    sz = sizing()
    w = QtWidgets.QCheckBox(text, parent)
    w.setStyleSheet(
        f"QCheckBox {{ color: {p['text_primary']}; font-size: {sz['font_size_sm']}px;"
        f" spacing: {sz['checkbox_spacing']}px; }}"
        f"QCheckBox::indicator {{ width: {sz['checkbox_size']}px;"
        f" height: {sz['checkbox_size']}px;"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_sm']}px;"
        f" background: {p['bg_card']}; }}"
        f"QCheckBox::indicator:hover {{ background: {p['bg_hover']}; }}"
        f"QCheckBox::indicator:checked {{ border-color: {p['accent']};"
        f" background: {p['accent']}; }}"
    )
    return w
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: PASS（含新增 3 用例）

- [ ] **Step 6: 迁移 webview_control 直写点**

`modules/webview_control/page.py` 顶部确认已 import `make_checkbox`（若无则加），L384-386 替换：
```python
from ui.widgets import make_checkbox  # 文件顶部 import 区

# L384-386（原 sw_btn = QtWidgets.QCheckBox("封禁") + setStyleSheet 两行）
sw_btn = make_checkbox("封禁")
sw_btn.setChecked(bool(r["blocked"]))
```
删除 `sw_btn.setStyleSheet("QCheckBox { spacing: 6px; }")` 一行。

- [ ] **Step 7: 跑相关测试 + 门禁**

Run:
```
.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py tests/test_webview_merged.py tests/test_style_guardrails.py -q
.venv\Scripts\python.exe scripts\audit_styles.py --check
```
Expected: 全绿 + `[audit] OK: 0 violations`

- [ ] **Step 8: Commit**

```bash
git add ui/widgets.py modules/webview_control/page.py core/theme/tokens.py tests/test_style_widgets.py
git commit -m "feat(ui): add make_checkbox factory and migrate webview block toggle"
```

---

### Task 2: make_tool_button 工厂 + todo_notes 清除键迁移

**Files:**
- Modify: `ui/widgets.py`（追加 make_tool_button）
- Modify: `modules/todo_notes/page_widget.py:1020-1031`（QToolButton 直写迁移）
- Test: `tests/test_style_tokens.py`（sizing 新令牌存在性）+ `tests/test_style_widgets.py`（工厂用例）

**Interfaces:**
- Consumes: `theme_palette()`（ghost 四元组）、`sizing()`（btn_height_sm/md/lg、font_size_sm）
- Produces: `make_tool_button(text="", *, kind="ghost", size="md", parent=None) -> QtWidgets.QToolButton`；kind 支持 `"ghost"`/`"default"`（与 make_button 语义一致）；`setAutoRaise(True)` 内置；`setCursor(PointingHandCursor)` 内置

- [ ] **Step 1: 写失败测试**

在 `tests/test_style_widgets.py` 追加：
```python
def test_make_tool_button_ghost(qapp):
    from ui.widgets import make_tool_button
    b = make_tool_button("×", kind="ghost", size="sm")
    assert isinstance(b, QtWidgets.QToolButton)
    assert b.text() == "×"
    assert b.autoRaise() is True
    qss = b.styleSheet()
    assert "border: none" in qss or "border:1px solid transparent" in qss.replace(" ", "")

def test_make_tool_button_default_has_tokens(qapp):
    from ui.widgets import make_tool_button
    from core.theme.tokens import theme_palette
    b = make_tool_button("x", kind="default", size="md")
    qss = b.styleSheet()
    assert theme_palette()["text_primary"] in qss
    assert "rgba(" not in qss
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: FAIL——ImportError: make_tool_button

- [ ] **Step 3: 实现 make_tool_button**

`ui/widgets.py` 追加：
```python
def make_tool_button(text="", *, kind="ghost", size="md", parent=None):
    """令牌化工具按钮。ghost=透明无边框；default=凹陷底+边框。autoRaise 内置。"""
    p = theme_palette()
    sz = sizing()
    h = {"sm": sz["btn_height_sm"], "md": sz["btn_height_md"],
         "lg": sz["btn_height_lg"]}[size]
    styles = {
        "ghost": ("transparent", p["text_primary"], "transparent",
                  p["bg_hover"], p["overlay_pressed"]),
        "default": (p["bg_control"], p["text_primary"], p["border"],
                    p["bg_hover"], p["overlay_pressed"]),
    }
    bg, fg, border, hover, pressed = styles[kind]
    b = QtWidgets.QToolButton(parent)
    b.setText(text)
    b.setAutoRaise(True)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.setFixedHeight(h)
    b.setStyleSheet(
        f"QToolButton {{ background: {bg}; color: {fg};"
        f" border: 1px solid {border}; border-radius: {sz['radius_md']}px;"
        f" padding: 0; font-size: {sz['font_size_sm']}px; }}"
        f"QToolButton:hover {{ background: {hover}; }}"
        f"QToolButton:pressed {{ background: {pressed}; }}"
    )
    return b
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: PASS

- [ ] **Step 5: 迁移 todo_notes 清除键**

`modules/todo_notes/page_widget.py` L1020-1031（关键不变量：ObjectName、18×18 令牌尺寸、_DueHoverFilter、layout、CellWidget 结构全部保留）：
```python
from ui.widgets import make_tool_button  # 文件顶部 import 区

# 替换 btn = QtWidgets.QToolButton(holder) + setObjectName + setText + setAutoRaise + setCursor + setStyleSheet 五行
btn = make_tool_button("×")                       # ghost + sm 高度
btn.setObjectName("todo_due_clear")
btn.setFixedSize(_sz["todo_due_clear_size"], _sz["todo_due_clear_size"])  # 覆盖为方形 18×18
```
删除 `setAutoRaise(True)`、`setCursor(...)`、`setStyleSheet("QToolButton { padding: 0; border: none; }")`（工厂已内置）。其余（clicked/visible/eventFilter/layout）不动。

- [ ] **Step 6: 跑相关测试 + 门禁**

Run:
```
.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py tests/test_todo_notes_ui.py tests/test_todo_notes_hover.py -q
.venv\Scripts\python.exe scripts\audit_styles.py --check
```
注意：`test_todo_notes_ui.py` 单独跑（分进程，勿与其他 todo/perf 混跑）。若 test_todo_notes_ui 因进程隔离需求跳过，以 test_todo_notes_hover.py + 其余 todo 文件的结果为准。

- [ ] **Step 7: Commit**

```bash
git add ui/widgets.py modules/todo_notes/page_widget.py tests/test_style_widgets.py
git commit -m "feat(ui): add make_tool_button factory and migrate todo due-clear key"
```

---

### Task 3: 第 3 层令牌：阴影/动效/圆角/窗口底色

**Files:**
- Modify: `core/theme/tokens.py`（theme_palette 两分支 + sizing + 新 motion_durations 函数）
- Test: `tests/test_theme_borders.py` 或新增 `tests/test_theme_motion_shadow.py`（若新增须登记 CI chunk）

**Interfaces:**
- Consumes: 现有 tokens 结构（_s() 缩放、rgba_to_qcolor）
- Produces:
  - theme_palette() 两分支新增：`card_shadow_color`（暗 `"rgba(0,0,0,0.28)"` / 亮 `"rgba(0,0,0,0.14)"`——Fluent 2 浅 14%/深 28%）
  - sizing() 新增：`shadow_blur=_s(38)`、`shadow_offset=_s(5)`（Fluent-M3U8 卡片 blur38/offset(0,5)）、`radius_xl=_s(12)`（Fluent 2 X-Large）
  - 新函数 `motion_durations() -> dict`：Fluent 2 八档 `{"xs":50,"sm":100,"md":150,"lg":200,"xl":250,"2xl":300,"3xl":400,"4xl":500}`（ms）
  - 窗口底色微调：亮 bg_app `rgba(245,245,245,0.92)` → `rgba(240,244,249,0.92)`、暗 bg_app `rgba(30,30,30,0.92)` → `rgba(32,32,32,0.92)`（Fluent-M3U8 实色 240,244,249 / 32,32,32 的带 alpha 版本）

- [ ] **Step 1: 写失败测试**

新增 `tests/test_theme_shadow_motion.py`（登记 CI chunk3，放在 test_style_guardrails.py 附近）：
```python
"""第3层视觉令牌：阴影/动效/圆角对齐/窗口底色。"""
from conftest import _force_dark, _restore_dark
from core.theme.tokens import sizing, theme_palette, motion_durations


def test_motion_durations_fluent2_octave():
    d = motion_durations()
    assert d == {"xs": 50, "sm": 100, "md": 150, "lg": 200,
                 "xl": 250, "2xl": 300, "3xl": 400, "4xl": 500}


def test_shadow_tokens_exist():
    sz = sizing()
    assert "shadow_blur" in sz and "shadow_offset" in sz and "radius_xl" in sz


def test_card_shadow_color_present_both_themes():
    from conftest import _force_dark
    try:
        _force_dark()
        light = theme_palette(False)
        dark = theme_palette(True)
        assert "card_shadow_color" in light and "card_shadow_color" in dark
        assert light["card_shadow_color"] != dark["card_shadow_color"]
    finally:
        _restore_dark()


def test_window_bg_aligned_fluent():
    p = theme_palette(False)
    assert "240,244,249" in p["bg_app"]      # 亮色 Fluent-M3U8
    p2 = theme_palette(True)
    assert "32,32,32" in p2["bg_app"]        # 暗色 Fluent-M3U8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_theme_shadow_motion.py -q`
Expected: FAIL（motion_durations ImportError / 键缺失 / bg_app 断言失败）

- [ ] **Step 3: 实现令牌**

`core/theme/tokens.py`：
1. sizing() 增加 `"shadow_blur": _s(38), "shadow_offset": _s(5), "radius_xl": _s(12)`（紧邻 radius_lg=_s(8) 之后）
2. theme_palette() 亮分支 `"bg_app": "rgba(245,245,245,0.92)"` → `"rgba(240,244,249,0.92)"`；暗分支 → `"rgba(32,32,32,0.92)"`
3. theme_palette() 亮分支（文本附近）加 `"card_shadow_color": "rgba(0,0,0,0.14)"`；暗分支加 `"card_shadow_color": "rgba(0,0,0,0.28)"`（两分支各加一条，注释「Fluent 2 阴影透明度浅14%/深28%」）
4. 新增函数（rgba_to_qcolor 之后）：
```python
def motion_durations():
    """Fluent 2 动效八档（ms）。xs=50 sm=100 md=150 lg=200 xl=250 2xl=300 3xl=400 4xl=500。"""
    return {"xs": 50, "sm": 100, "md": 150, "lg": 200,
            "xl": 250, "2xl": 300, "3xl": 400, "4xl": 500}
```

- [ ] **Step 4: 跑测试确认通过 + 登记 CI**

Run: `.venv\Scripts\python.exe -m pytest tests/test_theme_shadow_motion.py -q`
Expected: PASS

登记 `.github/workflows/python-app.yml` chunk3：把 `tests/test_style_guardrails.py` 前插入 `tests/test_theme_shadow_motion.py`。

- [ ] **Step 5: 守卫测试 + audit**

Run:
```
.venv\Scripts\python.exe -m pytest tests/test_style_guardrails.py tests/test_theme_tokens.py tests/test_theme_borders.py tests/test_theme_shadow_motion.py -q
.venv\Scripts\python.exe scripts\audit_styles.py --check
```
Expected: 全绿 + 0 violations（tokens.py 白名单，rgba 令牌允许）

- [ ] **Step 6: Commit**

```bash
git add core/theme/tokens.py tests/test_theme_shadow_motion.py .github/workflows/python-app.yml
git commit -m "feat(theme): add shadow/motion/radius-xl tokens and align window bg to Fluent-M3U8"
```

---

### Task 4: attach_card_shadow 封装 + 落地

**Files:**
- Modify: `ui/widgets.py`（追加 attach_card_shadow + make_card 加 shadow 参数）
- Test: `tests/test_style_widgets.py`
- 可选落地：`modules/rss_aggregator/page_preview.py` 或 `ui/home_tab`（卡片阴影；若触发审计/截图对比则做，否则仅封装）

**Interfaces:**
- Consumes: `theme_palette()["card_shadow_color"]`、`sizing()["shadow_blur"/"shadow_offset"]`、`rgba_to_qcolor()`
- Produces: `attach_card_shadow(widget) -> QtWidgets.QGraphicsDropShadowEffect`（blur=shadow_blur、offset=(0, shadow_offset)、color=card_shadow_color）；`make_card(*, parent=None, shadow=False)`——shadow=True 时自动 attach

- [ ] **Step 1: 写失败测试**

`tests/test_style_widgets.py` 追加：
```python
def test_attach_card_shadow_effect(qapp):
    from ui.widgets import attach_card_shadow
    from core.theme.tokens import sizing
    w = QtWidgets.QFrame()
    eff = attach_card_shadow(w)
    assert isinstance(eff, QtWidgets.QGraphicsDropShadowEffect)
    assert eff.blurRadius() == sizing()["shadow_blur"]
    assert eff.offset().y() == sizing()["shadow_offset"]
    assert w.graphicsEffect() is eff


def test_make_card_shadow_flag(qapp):
    from ui.widgets import make_card
    plain = make_card()
    assert plain.graphicsEffect() is None
    shadowed = make_card(shadow=True)
    assert isinstance(shadowed.graphicsEffect(), QtWidgets.QGraphicsDropShadowEffect)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: FAIL——ImportError: attach_card_shadow

- [ ] **Step 3: 实现**

`ui/widgets.py`：
```python
def attach_card_shadow(widget):
    """给卡片挂 Fluent 风格投影。blur/offset/色全部来自令牌。"""
    from core.theme.tokens import rgba_to_qcolor
    p = theme_palette()
    sz = sizing()
    eff = QtWidgets.QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(sz["shadow_blur"])
    eff.setOffset(0, sz["shadow_offset"])
    eff.setColor(rgba_to_qcolor(p["card_shadow_color"]))
    widget.setGraphicsEffect(eff)
    return eff
```
`make_card` 签名改 `def make_card(*, parent=None, shadow=False):` 并在 return 前：
```python
    if shadow:
        attach_card_shadow(frame)
    return frame
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py -q`
Expected: PASS

- [ ] **Step 5: 可选落地 + 截图对照**

对 rss 预览区/主页卡片启用 shadow=True（选 1-2 处视觉收益最大、风险最小的卡片）。改前截图 → 改后截图对比确认阴影不遮挡文字、1.6x 无截断。

- [ ] **Step 6: 门禁 + Commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_style_widgets.py tests/test_style_guardrails.py tests/test_rss_style.py -q` + `audit_styles.py --check`
```bash
git add ui/widgets.py <可选落地的模块文件> tests/test_style_widgets.py
git commit -m "feat(ui): add attach_card_shadow and make_card(shadow=True)"
```

---

### Task 5: rss styles.py 私有按钮样式收敛评估（黄金 QSS 锁定）

**Files:**
- Test: `tests/test_rss_style.py`（现有，追加黄金断言）
- 不改 `modules/rss_aggregator/styles.py`（决策：保留，API 不兼容 + 已令牌化合规）

**Interfaces:**
- Consumes: `_btn_primary_style(min_width=80, padding="6px 16px", radius=8, font_size=13)`、`_btn_style(...)`、`rss_style_vars()`
- Produces: 黄金 QSS 断言测试（锁定现状防回归）+ 评估结论（文档）

- [ ] **Step 1: 写黄金测试（锁定现状）**

`tests/test_rss_style.py` 追加：
```python
def test_rss_btn_primary_style_golden():
    """锁定 _btn_primary_style 现状：主强调按钮必须全令牌、无硬编码色。"""
    from modules.rss_aggregator.styles import _btn_primary_style
    qss = _btn_primary_style()
    assert "rss_accent" in qss or "{rss_accent}" in qss
    assert "border-radius" in qss
    import re
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", qss)   # 不允许 hex 硬编码
    assert "rgba(" not in qss.replace("rgba({", "")     # 只允许 {token} 间接引用


def test_rss_btn_style_checked_state_golden():
    from modules.rss_aggregator.styles import _btn_style
    qss = _btn_style()
    assert ":checked" in qss      # 次级按钮 checked 态（rss_accent 高亮）
```

- [ ] **Step 2: 跑测试确认通过（现状即黄金）**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rss_style.py -q`
Expected: PASS（若失败说明现有实现有硬编码，需按失败点修 styles.py 为令牌引用——这是本 Task 唯一可能触发的实现改动）

- [ ] **Step 3: 评估结论落档**

若 Step 2 全绿：styles.py 无硬编码、API 与 make_button 不兼容（min_width/padding/radius/font_size/checked/disabled 参数集不同）、20 处调用受控——决策「保留模块私有样式，不做强制收敛」，在 commit message 附注说明。

- [ ] **Step 4: Commit**

```bash
git add tests/test_rss_style.py
git commit -m "test(rss): lock golden QSS for private button styles"
```

---

## 验证与收尾（所有 Task 完成后）

- [ ] **Step 1: 全量门禁**

Run: `.venv\Scripts\python.exe scripts\audit_styles.py --check` + `.venv\Scripts\python.exe -m pytest tests/test_style_guardrails.py -v` + CI chunk3 相关文件 `-q`。Expected: 全绿 + 0 violations。

- [ ] **Step 2: 批量截图验收**

杀掉旧 GUI → `Start-Process .venv\Scripts\pythonw.exe main.py` → 暗色/亮色各截图（首页、webview 模块、todo_notes、rss 页），用 QImage 像素分析程序化验证（模型无法直接看图）：accent=teal 系、卡片阴影可见、无旧蓝。

- [ ] **Step 3: 最终提交聚合检查**

`git log --oneline -8` 应含：bedb0d3 + (a0d181a, e2365e3, bcc9d15) + 本计划 5 个 commit；`git status` 干净。