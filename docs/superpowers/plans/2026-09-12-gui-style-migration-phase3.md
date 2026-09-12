# GUI Style 存量迁移（阶段 3）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `scripts/styles_audit_baseline.json` 中 166 条存量样式违规逐模块迁移到 `theme_palette()`/`sizing()` 令牌体系，最终 audit 零违规、消除第三套调色板（qss_dark/qss_light 兜底）。

**Architecture:** 全量色值收敛到 `core/theme/tokens.py::theme_palette()`（函数式实时取明/暗），尺寸收敛到 `sizing()`（随字体缩放）。迁移按 spec 规定顺序 ①ui/ → ②perf_monitor → ③todo/sys_info/webview/translator → ④rss_aggregator 分批推进；每模块替换后明/暗截图对比 + 护栏测试回归。新增两条审计能力：`size_literal` 规则（QSS 内 px 尺寸字面量）与行内豁免注释（P-10，覆盖 QWebEngine JS / MCP 跨进程等非 Qt 渲染边界）。

**Tech Stack:** Python 3 / PySide6 / qfluentwidgets；运行时护栏 pytest（`tests/test_style_guardrails.py` 主题切换无残留 + 1.6x 无截断）。

**Spec:** `docs/superpowers/specs/2026-09-12-gui-style-unification-design.md`（第 4 节"阶段 3：存量迁移"、第 5 节"四道护栏"、第 6 节"验证方式"为本章依据）。前置基础设施：`docs/superpowers/plans/2026-09-12-gui-style-infrastructure.md`（已完成，8/8 任务，commit `e2dfcc3`..`e271d1b`）。

## 阶段 3 范围快照（数据源：`scripts/styles_audit_baseline.json`）

- **总量 166** = hex_color 137 + fixed_size 14 + hardcoded_qss 11 + private_palette 4
- **模块分布**：`rss_aggregator` 77（text_utils.py 48 独占）、`todo_notes` 19、ui/ 层 14（log_viewer 6 + settings_tab/log_ops 5 + module_pages 1 + log_build 1 + title_bar_kit 1）、`webview_control` 9、`win_maintenance` 8、`translator` 8、`page_selector` 6、`rss_store` 6、`mcp_server` 6、`perf_monitor` 5、`sys_info_widget` 4、`core` 2、`main.py` 1
- **private_palette 4 处**：`perf_monitor/bar.py:5` `_bar_text_color`、`rss_aggregator/text_utils.py:8` `_rss_colors`、`text_utils.py:149` `_rss_panel_colors`、`sys_info_widget.py:26` `_theme_colors`
- **fixed_size 14 处**：perf chart.py:19 / page.py:139、rss page_layout.py:158,188 / page_lifecycle.py:113,123,265 / sidebar.py:168,187、sys_info_widget.py:54、webview_control/page.py:161、ui/module_pages.py:45(48px)、ui/settings_tab/log_build.py:72(200px)、ui/title_bar_kit.py:29(28px)
- **hardcoded_qss 11 处**：page_selector/dialog_core.py:66、rss page_theme.py:68 / rows_item.py:96、todo date_theme.py:80 / page_widget.py:89、translator home.py:54,75 / llm_config.py:66 / page.py:101、webview_control/page.py:20、ui/log_viewer.py:85
- **高频唯一 hex（≥3 次）**：`#1a73e8`×14（Google 蓝，链接/状态蓝）、`#ff6b6b`×8、`#e6e6e6`×8、`#c5221f`×6、`#1967d2`×6、`#ffffff`×5、`#27ae60`×5、`#d93025`×5、`#fce8e6`/`#e6f4ea`×4、`#137333`×4、`#e8e8e8`/`#1f1f1f`×4、`#e74c3c`×4、`#2e7d32`×3、`#1178e0`×3、`#7fe0c0`×3、`#9a9a9a`×3、`#e8f0fe`×3、`#e67e22`×3、`#1e1e1e`×3、`#1a1a1a`×3、`#3498db`×3、`#e8710a`×3

## P-9 裁定（存量值与令牌不一致时的替换规则，全局指导）

存量 hex 与 `theme_palette()` 权威值不一致是常态（例：模块红 `#d93025` vs palette `danger` 暗 `#ff6b8a`/亮 `#e4506f`）。替换规则按优先级：

1. **语义归属既有 key**（模块红=危险、灰=次要文字、蓝=链接/强调）→ 直接替换为 palette 权威值，明/暗截图确认**非退化**（允许细微色差，禁止退化）。
2. **模块专属色无对应 key** → 遵循 AGENTS.md 规则 5：先在 `theme_palette()` 对应主题区新增命名 key（**保留原值**，零视觉变化），再引用。命名用 `<域>_<语义>`（如 `log_error`、`webview_allowed`、`calendar_bg`）。
3. **纯白 `#ffffff`**：仅用于"深底上的文字/选中前景"。若目标主题无纯白 key，新增 `white` key（两主题均 `#ffffff`）；禁止保留任何其他裸 hex。
4. 明暗主题同值的语义色（如 log 级别色、webview 状态色）→ 在亮/暗两区**同值**新增 key（单组语义 key，跨主题共用）。

## P-10 裁定（非 Qt 渲染边界豁免）

以下环境的色值**不进入 Qt 令牌流**，经审计行内豁免注释 + 档案记录豁免：
- `modules/page_selector/picker_js.py` 等 **QWebEngine JS 字符串**（浏览器沙箱内渲染，无 python 侧令牌访问）
- **MCP 服务**（`mcp_server/*`）跨进程返回的色值数据（下发给远端客户端，非本进程 Qt 样式）

豁免机制：audit 增加**行内豁免注释**解析（`# audit-exempt: <reason>`，见 T7）。豁免文件仍受其余规则约束，仅标注行不再计数。此裁定使 JS/MCP 边界色不被"为迁而迁"（硬塞令牌流反而引入跨进程注入复杂度），成本为零（这些行本就不构成 Qt 样式违规）。

## Global Constraints

1. 禁止新增任何硬编码颜色（#hex）或尺寸（setFixedHeight(数字)）——除 `core/theme/tokens.py`、`ui/widgets.py` 内的令牌定义。
2. Qt 导入一律走 `from core.qt_bootstrap import import_qt`，模式：`_, QtCore, QtGui, QtWidgets = import_qt()`。
3. 尺寸/字号必须经 `sizing()` 令牌，禁止手写 `font-size: 13px`、`padding: 5px 14px`。
4. 模块禁止定义私有调色板（`_xxx_colors()`）；颜色一律 `from core.theme.tokens import theme_palette`。
5. 测试文件命名 `tests/test_style_*.py`。
6. 每个任务结束跑 `python scripts/audit_styles.py --check`（新增违规即失败）与 `pytest tests/test_style_guardrails.py -v`（主题切换无残留、1.6x 无截断），并提交；提交信息用 `feat(style):`/`refactor(style):`/`test(style):` 前缀。
7. **迁移保持值层面零回归**：每模块替换后 `pytest tests/test_style_guardrails.py tests/test_perf_monitor_ui.py -v` 全绿；明/暗主题截图对比（GUI 运行时工具：`yzplan_screenshot_yzplan` / `yzplan_screenshot_module`），人工确认无退化。
8. **audit 基线重建纪律**：任何新规则引入、豁免变更后必须 `python scripts/audit_styles.py --init` 重建基线 + `--check` 验证 exit 0；提交信息标注 `baseline: N→M`（N/M 为账户性变动，非回归）。
9. **rss_aggregator 协作者活跃改动**（`modules/rss_aggregator/*` + `tests/test_rss_sidebar.py` 有未提交改动）：T8 开始前必须确认协作者未提交改动已提交或冻结快照，避免迁移与协作改动冲突。
10. **TDD**：先写失败测试 → 实现 → 绿 → 提交；红阶段证据写入每个任务的报告文件。

---

### Task 1: sizing() 补齐内边距类令牌 + 工厂消除 px 字面量 + audit `size_literal` 规则（I-1 + M-2 修复）

**Files:**
- Modify: `core/theme/tokens.py:104-122`（sizing() 增 5 key）
- Modify: `ui/widgets.py:52,68,69,98`（引用新令牌）
- Modify: `scripts/audit_styles.py`（新增 `size_literal` 规则）
- Test: `tests/test_style_widgets.py`、`tests/test_style_audit.py`

**Interfaces:**
- Consumes: `sizing()`（`tokens.py`，已存在）、audit 规则框架（`enum` 4 规则 + 正则扫描，已存在）
- Produces: `sizing()` 新 key `input_h_padding=10`、`combo_padding="4px 10px"`、`combo_drop_width=20`、`chip_border_extra=10`、`chip_padding_h=10`（均走 `_s()` 缩放）；audit 新规则 `size_literal`；widgets 工厂 QSS 零裸 px 数字

- [ ] **Step 1: 写失败测试——audit `size_literal` 规则能捕获 QSS 内数字 px**

`tests/test_style_audit.py` 增加：

```python
SIZE_QSS_SAMPLE = 'padding: 4px 10px; font-size: 11px;'  # 尺寸字面量应捕获

def test_size_literal_rule_catches_qss_px(dark_theme, tmp_path):
    from scripts.audit_styles import scan_file, Rule
    p = tmp_path / "sample.py"
    p.write_text(f'w.setStyleSheet("QLineEdit {{ {SIZE_QSS_SAMPLE} }}")', encoding="utf-8")
    hits = scan_file(str(p), dark_theme)
    assert any(h["rule"] == Rule.SIZE_LITERAL.value for h in hits)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_style_audit.py::test_size_literal_rule_catches_qss_px -v`
Expected: FAIL（`Rule.SIZE_LITERAL` 不存在）

- [ ] **Step 3: audit 实现 `size_literal` 规则**

`scripts/audit_styles.py`：`enum.Enum` 增 `SIZE_LITERAL = "size_literal"`；规则列表增：

```python
# QSS 内数字 px 尺寸字面量（padding/width/margin/border-radius/font-size 等）
RE_SIZE_LITERAL = re.compile(r"(?:padding|margin|width|height|border-radius|font-size|line-height):\s*\d+px", re.I)
```

扫描函数对每行同时跑 hex 与 size 匹配，命中即在 `"rules"` 列表记录；`size_literal` 与 `hex_color` 一样受 whitelist 豁免。

- [ ] **Step 4: widgets.py 引用新令牌（消除 L52/L68/L69/L98 字面量）**

`ui/widgets.py` 四处替换：

```python
# L49-52 make_line_edit
f" padding: {sz['input_height'] // 5}px {sz['input_h_padding']}px;"          # 10 → input_h_padding
# L65-69 make_combo
f" padding: {sz['combo_padding']}; font-size: {sz['font_size_sm']}px; }}"     # 4px 10px → combo_padding
f"QComboBox::drop-down {{ border: none; width: {sz['combo_drop_width']}px; }}"  # 20 → combo_drop_width
# L96-99 make_status_chip
f" padding: {sz['radius_sm'] // 2}px {sz['chip_padding_h']}px;"
f" border-radius: {sz['radius_sm'] + sz['chip_border_extra']}px;"             # +10 → chip_border_extra；split()[1] → chip_padding_h（M-2）
```

`core/theme/tokens.py` sizing() 增：

```python
"input_h_padding": _s(10),
"combo_padding": f"{_s(4)}px {_s(10)}px",
"combo_drop_width": _s(20),
"chip_border_extra": _s(10),
"chip_padding_h": _s(10),
```

- [ ] **Step 5: 加护栏——断言工厂 QSS 无裸 px 数字**

`tests/test_style_widgets.py` 增：

```python
def test_factories_qss_have_no_bare_px_literals(dark_theme):
    from ui.widgets import make_combo, make_line_edit, make_status_chip
    import re
    for w in (make_line_edit(), make_combo(), make_status_chip("x")):
        qss = w.styleSheet()
        assert not re.search(r"(?:padding|width|border-radius):\s*\d+px", qss), qss
```

- [ ] **Step 6: 重建基线 + 全绿验证**

Run: `python scripts/audit_styles.py --init && python scripts/audit_styles.py --check && pytest tests/test_style_audit.py tests/test_style_widgets.py -v`
Expected: `--check` exit 0；基线 total 从 166 增至含新规则捕获的存量（`baseline: 166→实测`，账户性增长）；两测试文件全绿。自检：`core/theme/tokens.py`/`ui/widgets.py` 在 whitelist，工厂 QSS 新断言防回归。

- [ ] **Step 7: 提交**

```bash
git add core/theme/tokens.py ui/widgets.py scripts/audit_styles.py tests/test_style_audit.py tests/test_style_widgets.py scripts/styles_audit_baseline.json
git commit -m "feat(style): sizing() 补齐内边距类令牌 + audit size_literal 规则；baseline 166→N"
```

---

### Task 2: 测试加固——恒真断言修复 + P-3 双 patch 一致性（I-2 前置、I-3、M-1、M-3）

**Files:**
- Modify: `tests/test_style_tokens.py`（I-2 恒真测试改结构断言）
- Modify: `tests/test_style_widgets.py:47`（I-3 第二断言）、`tests/test_style_widgets.py:29-31`（M-1 双 patch）、`tests/test_style_audit.py:2-4`（M-3 未用导入）

**Interfaces:**
- Consumes: `theme_palette()`、`_theme_colors()`（perf 别名，T7 已合并）、`_force_dark`（tokens 版双 patch）
- Produces: 三个测试文件加固；**不产生生产代码改动**

- [ ] **Step 1: I-2 改结构断言——合并两个恒真测试**

`tests/test_style_tokens.py`：删除 `test_palette_matches_perf_monitor_baseline` 与 `test_perf_monitor_colors_alias_global_palette` 的恒真值断言，替换为：

```python
def test_perf_palette_is_superset_of_global_palette(dark_theme):
    """结构断言：perf 别名必须覆盖全局色板全部 key（防退回独立色板/丢 key）。"""
    from modules.perf_monitor.styles import _theme_colors
    tc = _theme_colors()
    gp = theme_palette()
    assert set(tc.keys()) >= set(gp.keys())
    # perf 专属扩展 key 必须存在
    for k in ("accent_pid", "accent_cpu", "accent_mem", "accent_thr",
              "accent_hdl", "accent_uptime", "group_border", "group_bg",
              "grid_color", "bar_colors"):
        assert k in tc
```

> 注：perf 的 **5 个旧 key 别名映射断言延迟到 T4**（T4 收回别名时一并改为"调用点已用全局 key"断言，避免本任务与 T4 互踩）。

- [ ] **Step 2: I-3 修第二断言——QSS hex 全须来自调色板**

`tests/test_style_widgets.py:40-52` 的 `test_make_button_primary_uses_accents` 第二断言改为：

```python
from tests.test_style_tokens import _qss_colors  # 或本文件复制同 helper
...
    qss_hexes = _qss_colors(b.styleSheet())
    assert all(c in p.values() or c == "#ffffff" for c in qss_hexes)
```

（原 `"#3aa6ff" not in qss or "#3aa6ff" == p["accent"]` 在暗色下恒真，已放弃。）

- [ ] **Step 3: M-1 双 patch + M-3 清导入**

`tests/test_style_widgets.py::_force_dark`（29-31 行）补包级 patch，与 P-3 一致：

```python
def _force_dark(dark: bool):
    import core.theme as pkg
    from core import theme as base_mod
    base_mod.resolve_dark = lambda mode: dark
    pkg.resolve_dark = lambda mode: dark
    return True
```

`tests/test_style_audit.py` 删除未使用的 `import json` / `import subprocess` / `import sys`（保留用到的）。

- [ ] **Step 4: 红阶段验证加固测试可捕获注入违规**

Run: 临时在 `ui/widgets.py` `make_button` 的 QSS 注入 `color: #3aa6ff;` → `pytest tests/test_style_widgets.py::test_make_button_primary_uses_accents -v` → **Expected FAIL**（注入被新断言捕获）；移除注入 → PASS。记录该红→绿证据（红色证据为"注入违规则失败"，属加固测试的标准演示方式）。

- [ ] **Step 5: 全绿 + 提交**

Run: `python scripts/audit_styles.py --check && pytest tests/test_style_tokens.py tests/test_style_widgets.py tests/test_style_guardrails.py -v`
Expected: exit 0（测试文件改动不增违规）+ 全绿。

```bash
git add tests/test_style_tokens.py tests/test_style_widgets.py tests/test_style_audit.py
git commit -m "test(style): 加固恒真断言（I-2/I-3）+ _force_dark 双 patch 一致（M-1）+ 清未用导入（M-3）"
```

---

### Task 3: ui/ 层迁移（spec 顺序 ①，14 条）

**Files:** `ui/log_viewer.py`(6)、`ui/settings_tab/log_ops.py`(5)、`ui/module_pages.py`(1)、`ui/settings_tab/log_build.py`(1)、`ui/title_bar_kit.py`(1)

**Interfaces:**
- Consumes: `theme_palette()`（`info/success/warning/danger/text_secondary/text_disabled/accent`）、`sizing()`（新 key `toolbar_height`、`title_bar_height`、`log_table_min_height`，本任务在 tokens.py 新增）
- Produces: 5 文件 audit 归零；`sizing()` 新增 3 key

- [ ] **Step 1: tokens.py 新增 3 个尺寸 key + log 级别色 key**

```python
# sizing()
"toolbar_height": _s(48),        # ui/module_pages.py:45 统一 FluentTitleBar 高度
"title_bar_height": _s(28),      # ui/title_bar_kit.py:29
"log_table_min_height": _s(200), # ui/settings_tab/log_build.py:72

# theme_palette() 亮/暗两区追加（P-9 情形 4：明暗同值语义色）
"log_info": "#1a73e8",
"log_warning": "#f9a825",
"log_error": "#c5221f",
"log_critical": "#7b1fa2",
"log_source": "#1967d2",
```

- [ ] **Step 2: log_viewer.py + log_ops.py——级别色与 hardcoded_qss 接入令牌**

`ui/log_viewer.py:222-225,243` 与 `ui/settings_tab/log_ops.py:34-37,55`：
- 级别映射 `"INFO": "#1a73e8"` → `p["log_info"]`（模块内函数建 `LOG_LEVEL_COLORS = {"INFO": p["log_info"], ...}` 或直接引用，保持一致风格）
- `source_item.setForeground(QtGui.QColor("#1967d2"))` → `QtGui.QColor(p["log_source"])`
- `ui/log_viewer.py:85` `self.log_table.setStyleSheet(...)` 硬编码 QSS 字符串 → QSS 中所有 hex 改为 `{}` 格式化引用 `p[...]`；若该 QSS 为表格整体样式，改用 `ui/widgets.py` 工厂或 `p` 令牌拼装（与 settings_tab/log_ops.py:85 同模式）

- [ ] **Step 3: module_pages / title_bar_kit / log_build——fixed_size 换令牌**

```python
# ui/module_pages.py:45
tb.setFixedHeight(sz["toolbar_height"])          # 48 → toolbar_height
# ui/title_bar_kit.py:29
self.setFixedHeight(sz["title_bar_height"])      # 28 → title_bar_height
# ui/settings_tab/log_build.py:72
self.log_table.setMinimumHeight(sz["log_table_min_height"])  # 200 → log_table_min_height
```

- [ ] **Step 4: 验证 + 截图对比**

Run: `python scripts/audit_styles.py --check`（5 文件违规归零，总量 166→141 区域）→ `pytest tests/test_style_guardrails.py tests/test_perf_monitor_ui.py -v`
Expected: exit 0；护栏全绿。截图：`yzplan_screenshot_yzplan`（明/暗各一）+ `yzplan_logs_get` 确认无异常；人工确认 log 页、设置页日志 tab、标题栏、模块页无视觉退化。

- [ ] **Step 5: 提交**

```bash
git add core/theme/tokens.py ui/log_viewer.py ui/settings_tab/log_ops.py ui/settings_tab/log_build.py ui/module_pages.py ui/title_bar_kit.py
git commit -m "refactor(style): ui/ 层颜色/尺寸接入令牌（log 级别色 + toolbar/titlebar/logtable 尺寸）"
```

---

### Task 4: perf_monitor 收尾（spec 顺序 ②，5 条 + 别名收回）

**Files:** `modules/perf_monitor/styles.py`、`modules/perf_monitor/bar.py`、`modules/perf_monitor/cards.py`、`modules/perf_monitor/chart.py`、`modules/perf_monitor/page.py`、`core/theme/tokens.py`、`scripts/audit_styles.py`（whitelist 删行）、`tests/test_perf_monitor_ui.py`、`tests/test_style_tokens.py`

**Interfaces:**
- Consumes: Task 1 `size_literal` 规则、Task 2 结构断言测试
- Produces: `styles.py` 零 #hex、`_theme_colors` 改名 `perf_palette()`（不再匹配 private_palette regex）、whitelist 移除 `modules/perf_monitor/styles.py` 行、5 处调用点消费全局 key

- [ ] **Step 1: perf 专属扩展色并入 theme_palette()（P-9 情形 2，保原值）**

`core/theme/tokens.py` 亮/暗两区追加（perf 图表专区，注释标注 `# perf_monitor 图表扩展`）：

```python
# 暗色区 追加
"perf_accent_pid": "#5b8cff", "perf_accent_cpu": "#25c9a0", "perf_accent_mem": "#a06bff",
"perf_accent_thr": "#ffab40", "perf_accent_hdl": "#ff6b8a", "perf_accent_uptime": "#4fd97a",
"perf_group_border": "rgba(255,255,255,0.12)", "perf_group_bg": "rgba(255,255,255,0.04)",
"perf_grid_color": "rgba(255,255,255,0.06)", "perf_bar_colors": [(0,180,80),(60,170,50),(180,160,0),(220,120,0),(220,60,40)],
# 亮色区 追加
"perf_accent_pid": "#4a77f5", "perf_accent_cpu": "#12a582", "perf_accent_mem": "#7c3aed",
"perf_accent_thr": "#e08a1e", "perf_accent_hdl": "#e4506f", "perf_accent_uptime": "#2f9e5a",
"perf_group_border": "rgba(0,0,0,0.10)", "perf_group_bg": "rgba(0,0,0,0.02)",
"perf_grid_color": "rgba(0,0,0,0.06)", "perf_bar_colors": [(34,160,70),(70,150,40),(200,160,0),(210,110,0),(210,50,30)],
```

- [ ] **Step 2: styles.py 别名层收敛 + 改名**

`modules/perf_monitor/styles.py`：`_theme_colors()` 改 `perf_palette()`：

```python
def perf_palette():
    """perf 图表色板 = 全局色板 + perf 图表扩展（值全部来自 theme_palette）。"""
    p = dict(theme_palette())
    return p  # 扩展 key 已在 theme_palette 内（perf_* 前缀）
```

删除 5 个旧 key 映射块（`card_bg/card_border/ctrl_bg/ctrl_border/sel_bg` 不再产出——**调用点同步改**）；删除全部 perf 扩展字面量（改为 `p["perf_accent_pid"]` 等）。文件内 5 处消费旧 key 的调用点改为全局 key：`card_bg→bg_card`、`card_border→border`、`ctrl_bg→bg_control`、`ctrl_border→border`、`sel_bg→bg_selected`。

- [ ] **Step 3: bar/cards/chart/page 存量 hex + private_palette 收尾**

- `modules/perf_monitor/bar.py:5` `_bar_text_color`：内部 hex → 改读 `perf_palette()` 或全局 key；重命名避免匹配 private_palette regex（如 `_bar_text_style`，或保留函数名 + whitelist 注释豁免——推荐改名，函数为非色板函数）
- `bar.py` 其余 1 条 hex、`cards.py:?` 1 条、`chart.py:?` 1 条、`page.py:?` 1 条 hex → 全局/perf key 引用；`chart.py:19`、`page.py:139` fixed → `sizing()`（chart 高度/宽度语义，补相应 sizing key 或复用 `btn_height_*`，按实际语义）

- [ ] **Step 4: whitelist 删行 + 测试联动**

- `scripts/audit_styles.py` whitelist 删除 `modules/perf_monitor/styles.py` 行（styles.py 已零字面量）
- `tests/test_perf_monitor_ui.py::test_theme_colors_returns_dict`：`_theme_colors` 引用改 `perf_palette`；断言 key 集更新为全局 key 并集（`dark` + 全局 key + `perf_*` 与 `bar_colors` 等锚点）
- `tests/test_style_tokens.py`（Task 2 结构断言）：`_theme_colors` 引用同步改 `perf_palette`

- [ ] **Step 5: 红→绿验证**

Run: 红阶段——临时把 `perf_palette` 改回返回旧值表 → `pytest tests/test_style_tokens.py::test_perf_palette_is_superset_of_global_palette -v` 应 FAIL；恢复实现 → PASS。随后 `python scripts/audit_styles.py --init && python scripts/audit_styles.py --check`（`baseline: N→M`）→ `pytest tests/test_style_tokens.py tests/test_perf_monitor_ui.py tests/test_style_guardrails.py -v` 全绿。截图 perf 模块明/暗（`yzplan_screenshot_module module_id=perf_monitor`）确认零视觉漂移。

- [ ] **Step 6: 提交**

```bash
git add core/theme/tokens.py modules/perf_monitor/styles.py modules/perf_monitor/bar.py modules/perf_monitor/cards.py modules/perf_monitor/chart.py modules/perf_monitor/page.py scripts/audit_styles.py scripts/styles_audit_baseline.json tests/test_perf_monitor_ui.py tests/test_style_tokens.py
git commit -m "refactor(style): perf_monitor 收回旧 key 别名，扩展色并入全局色板；baseline N→M"
```

---

### Task 5: todo_notes + sys_info 迁移（spec 顺序 ③ 前半，26 条）

**Files:** `modules/todo_notes/date_theme.py`(13)、`modules/todo_notes/page_widget.py`(5)、`modules/todo_notes/delegate.py`(3)、`modules/todo_notes/constants.py`(1)、`modules/sys_info_widget.py`(4)

**Interfaces:**
- Consumes: `theme_palette()`（`bg_app/bg_card/bg_control/bg_hover/text_primary/text_secondary/accent/success/warning/danger/bg_selected/border`）、`sizing()`
- Produces: 5 文件 audit 归零；日历专属色 key 新增

- [ ] **Step 1: 日历主题映射（P-9 情形 1 为主 + 情形 2 补 key）**

`modules/todo_notes/date_theme.py:18-31` 的 QCalendarWidget 暗色 QSS（`#1e1e1e/#232323/#2b2b2b/#e6e6e6/#d9e7f7/#3a6ea5`）：值语义等价全局令牌的直映射：

| 存量值 | 目标令牌 |
|---|---|
| `#1e1e1e`（日历底层） | `bg_card`（暗 `rgba(255,255,255,0.06)` 若视觉差异大，新增 `calendar_bg` 保原值） |
| `#232323`（导航栏/表头） | `bg_control`（暗 `0.05`）同判 |
| `#2b2b2b`（spinbox/menu） | `bg_control` 同判 |
| `#e6e6e6`（文字） | `text_primary`（暗 `#e6e6e6` 恰等 ✓） |
| `#3a6ea5`（暗选中背景） | `bg_selected`（暗 `rgba(0,120,215,0.25)`）同判，或 `calendar_sel_bg` |
| `#d9e7f7`/`#1a1a1a`（亮选中） | `bg_selected` 亮 / `text_primary` 亮（`#1a1a1a` 恰等 ✓） |
| 亮色分支 L81 `QDateEdit { color: #e6e6e6/#1a1a1a }` | `text_primary`（明暗各自） |

> **执行指示**：迁移中每处判断"直映射（色差可接受）还是新增 `calendar_*` key 保原值"；截图对比日历控件明/暗后定夺。凡选择新增 key 的一律进 `theme_palette()` 并保原值（P-9 情形 2）。

- [ ] **Step 2: todo_notes 其余 hex + hardcoded_qss**

- `delegate.py:112,114,282`（`#27ae60/#3498db/#8e44ad` 勾选/进行/分类色）与 `page_widget.py:177,197,199,207`（`#8e44ad/#e74c3c/#e67e22/#27ae60/#3498db`）→ 语义映射：完成绿→`success`（暗 `#4fd97a`/亮 `#2f9e5a`，若不可接受新增 `todo_done`）；进行蓝→`info`；紧急红→`danger`；逾期橙→`warning`；分类紫→新增 `todo_category`（保原值 `#8e44ad`）
- `page_widget.py:89`、`date_theme.py:80` hardcoded_qss → 令牌拼装
- `constants.py:?` hex → 令牌引用

- [ ] **Step 3: sys_info_widget 私有色板收尾**

`modules/sys_info_widget.py:26` `_theme_colors` → 改 `theme_palette()` 引用（同名改造，如 `_sysinfo_palette()` 返回全局拷贝或直接内联引用）；其余 hex/fixed（:54 `setFixedHeight`）→ `sizing()` 语义 key。

- [ ] **Step 4: 验证 + 截图对比（todo 页 + 系统信息页 明/暗）**

Run: `python scripts/audit_styles.py --check`（5 文件归零）→ `pytest tests/test_style_guardrails.py -v` → 截图对比日历/列表/状态色。
Expected: exit 0 + 护栏绿 + 无退化（日历暗色块与状态色为人工关注点，色差不超 3% L\* 差视为无退化）。

- [ ] **Step 5: 提交**

```bash
git add core/theme/tokens.py modules/todo_notes/date_theme.py modules/todo_notes/page_widget.py modules/todo_notes/delegate.py modules/todo_notes/constants.py modules/sys_info_widget.py
git commit -m "refactor(style): todo_notes/sys_info 颜色与日历尺寸接入令牌"
```

---

### Task 6: webview_control + translator 迁移（spec 顺序 ③ 后半，17 条）

**Files:** `modules/webview_control/constants.py`(3)、`modules/webview_control/page.py`(4)、`modules/translator/home.py`(4)、`modules/translator/llm_config.py`(2)、`modules/translator/page.py`(2)

**Interfaces:**
- Consumes: `theme_palette()`（`warning/success/danger/text_secondary/text_disabled`）、`sizing()`
- Produces: 5 文件 audit 归零；webview 状态色 key（`webview_pending/webview_allowed/webview_blocked`）、translator 状态色 key（`status_warning/status_error/status_info`，与 T7 win_maintenance 共用）

- [ ] **Step 1: tokens.py 新增状态色 key（P-9 情形 2+4，明暗同值）**

```python
# 亮/暗两区同值追加
"webview_pending": "#e67e22", "webview_allowed": "#27ae60", "webview_blocked": "#e74c3c",
"status_warning": "#e8710a", "status_error": "#d93025", "status_info": "#1a73e8",
```

- [ ] **Step 2: webview_control 迁移**

- `constants.py:19-21`（`pending/allowed/blocked` 映射字典）→ `{"pending": p["webview_pending"], ...}`
- `page.py:106,112`（`setForeground(QColor("#e74c3c"/"#27ae60"))`）→ `p["webview_blocked"/"webview_allowed"]`
- `page.py:161` `setFixedHeight(30)` → `sz["input_height"]`（30 恰等 ✓）
- `page.py:20` hardcoded_qss（`"color: #888;"`）→ `p["text_secondary"]`

- [ ] **Step 3: translator 迁移**

- `home.py:54`、`llm_config.py:66`（`color: #d93025` 警告红）→ `p["status_error"]`
- `home.py:75`、`page.py:101`（`color: #888`）→ `p["text_secondary"]`
- `page.py:192`（点状 `color: #34a853; font-size: 16px;`——注意**font-size 字段**：16px 无 sizing 对应 → 改 `{sz['font_size_lg']}px`，色→`success` 或新增 `translator_ok`）——此条同时含 size_literal，一并处理

- [ ] **Step 4: 验证 + 截图对比（webview 控制页 + 翻译页 明/暗）**

Run: `python scripts/audit_styles.py --check` → `pytest tests/test_style_guardrails.py -v` → 截图对比状态色/警告色。

- [ ] **Step 5: 提交**

```bash
git add core/theme/tokens.py modules/webview_control/constants.py modules/webview_control/page.py modules/translator/home.py modules/translator/llm_config.py modules/translator/page.py
git commit -m "refactor(style): webview_control/translator 状态色与尺寸接入令牌"
```

---

### Task 7: 其余中小模块 + 审计行内豁免机制（P-10 落地，29 条）

**Files:** `modules/win_maintenance/home.py`(3)、`modules/win_maintenance/page.py`(5)、`modules/page_selector/picker_js.py`(4)、`modules/page_selector/dialog_core.py`(2)、`modules/rss_store/store.py`(6)、`mcp_server/tools_rss_rules.py`(4)、`mcp_server/rss_rules_impl.py`(2)、`core/constants.py`(1)、`core/theme/app_theme.py`(1)、`main.py`(1)、`scripts/audit_styles.py`

**Interfaces:**
- Consumes: `status_*` key（Task 6）、audit 规则框架
- Produces: `scripts/audit_styles.py` 支持**行内豁免注释** `# audit-exempt <reason>`；JS/MCP 边界行豁免；10 文件 audit 归零（豁免行除外）

- [ ] **Step 1: audit 行内豁免机制**

`scripts/audit_styles.py` 扫描逻辑：命中违规行时，若该行尾随（或前一行）含 `# audit-exempt` 注释，跳过计数。实现示例：

```python
RE_EXEMPT = re.compile(r"#\s*audit-exempt\s*\S.*$")
...
def _is_exempt(line: str) -> bool:
    return bool(RE_EXEMPT.search(line))
```

匹配循环内：`if _is_exempt(line): continue`。加测试：临时文件含 `QColor("#1a73e8")  # audit-exempt: JS 桥接色值` → `scan_file` 不报该行。

- [ ] **Step 2: JS / MCP 边界豁免（P-10）**

- `modules/page_selector/picker_js.py:?`（4 条 hex，QWebEngine JS 字符串）→ 每行追加 `# audit-exempt: QWebEngine JS 沙箱内渲染，无 Qt 令牌访问`
- `mcp_server/tools_rss_rules.py`(4) + `mcp_server/rss_rules_impl.py`(2) 的 hex → 若为下发给远端客户端的色值数据，同样追加 `# audit-exempt: MCP 跨进程数据色值，非本进程 Qt 样式`

- [ ] **Step 3: win_maintenance + rss_store + page_selector 迁移**

- `win_maintenance/home.py:15-17`、`page.py:24-26,179,181`（`#d93025/#e8710a/#1a73e8` 错误/警告/信息）→ `p["status_error"]/p["status_warning"]/p["status_info"]`
- `rss_store/store.py`(6) → 按语义映射常见色（`#27ae60/#e74c3c/#ff6b6b 等`→success/danger 或新增 `rss_*` key 保原值，截图判）
- `page_selector/dialog_core.py:66` hardcoded_qss + 2 hex → 令牌拼装
- `core/constants.py`、`core/theme/app_theme.py`、`main.py` 各 1-2 条 → 全局引用（app_theme 内的若是主题注册色值，评估并入 theme_palette 权威源）

- [ ] **Step 4: 重建基线 + 验证 + 提交**

Run: `python scripts/audit_styles.py --init && python scripts/audit_styles.py --check`（豁免行从基线剔除，`baseline: N→M`）→ `pytest tests/test_style_audit.py tests/test_style_guardrails.py -v` → 截图 win_maintenance 页明/暗。

```bash
git add scripts/audit_styles.py scripts/styles_audit_baseline.json modules/win_maintenance/home.py modules/win_maintenance/page.py modules/page_selector/picker_js.py modules/page_selector/dialog_core.py modules/rss_store/store.py mcp_server/tools_rss_rules.py mcp_server/rss_rules_impl.py core/constants.py core/theme/app_theme.py main.py tests/test_style_audit.py
git commit -m "refactor(style): 状态色统一 status_* + JS/MCP 边界行内豁免（P-10）；baseline N→M"
```

---

### Task 8: rss_aggregator 迁移（spec 顺序 ④，77 条，最复杂）——前置门槛

**前置门槛（gate）**：确认协作者未提交改动（`modules/rss_aggregator/*` 5 文件 + `tests/test_rss_sidebar.py`）已提交或冻结。**未确认前不得开始本任务**。

**Files 分组：**

- **8A. 主色板**：`modules/rss_aggregator/text_utils.py`（48 hex + `_rss_colors` + `_rss_panel_colors`）
- **8B. 主题/布局**：`page_theme.py`(4+qss:68)、`page_preview.py`(8)、`styles.py`(2)、`page_layout.py`(2+fixed:158,188)、`page.py`(2)、`rows_item.py`(2+qss:96)
- **8C. 侧栏/生命周期/对话框**：`sidebar.py`(2+fixed:168,187)、`page_lifecycle.py`(3+fixed:113,123,265)、`dialogs/e.py`(4)

**Interfaces:**
- Consumes: Task 1 `size_literal`、Task 6 `status_*`、`theme_palette()`（rss 专区）
- Produces: `text_utils.py` 双私有色板 → `theme_palette()` 的 `rss_*` 专区；rss 全部文件 audit 归零；护栏 C（spec:98 `_rss_colors()` 相关颜色全部来自 `theme_palette()`）成立

- [ ] **Step 0（gate）**: 执行 `git status`；若 `modules/rss_aggregator/*` 存在未提交改动 → 暂停，与用户/协作者确认提交或冻结后再继续。

- [ ] **Step 1: `_rss_colors()`/`_rss_panel_colors()` 并入 theme_palette() rss 专区（P-9 情形 2，保原值）**

`core/theme/tokens.py` 亮/暗两区追加 `rss_*` 专区（key 集合由 `text_utils.py:8,149` 两个函数现存返回键穷举——执行时读取函数体，逐键保原值进两主题区，标注 `# rss_aggregator 专区`）。`text_utils.py` 两个函数改为：

```python
def _rss_colors():
    return dict(theme_palette())  # rss_* 专区 key 已在全局色板内
# _rss_panel_colors 同理
```

删除函数内全部 hex 字面量；深度约 48 条 hex 的使用点改为经 `_rss_colors()` 结果取 key（最小改动面：保持函数签名与既有调用契约不变）。

- [ ] **Step 2: 8B 主题/布局组迁移**

- `page_theme.py:68`、`rows_item.py:96` hardcoded_qss → 令牌拼装（表格/行样式）
- `page_preview.py`(8)、`styles.py`(2)、`page_layout.py`(2) 的 hex → `p["rss_*"]` 或通用 key
- `page_layout.py:158,188`、`page_lifecycle.py:113,123,265`、`sidebar.py:168,187` fixed → `sizing()` 语义 key（按实际控件语义补 sizing key，如行高/侧栏宽度）

- [ ] **Step 3: 8C 侧栏/生命周期/对话框迁移**

- `sidebar.py`、`page_lifecycle.py` 其余 hex → 令牌；`dialogs/e.py`(4) → 令牌

- [ ] **Step 4: 护栏 C 断言（spec:98）**

`tests/test_style_guardrails.py` 增：

```python
def test_rss_colors_come_from_global_palette(dark_theme):
    """RSS 复杂控件：_rss_colors() 全部 key 来自 theme_palette() 的 rss 专区。"""
    from modules.rss_aggregator.text_utils import _rss_colors
    gp = theme_palette()
    tc = _rss_colors()
    assert set(tc.keys()) <= set(gp.keys())          # 无私有新增
    for k in tc:
        assert tc[k] == gp[k]                          # 值同源
```

- [ ] **Step 5: 验证（每子组）**

Run per sub-group: `python scripts/audit_styles.py --check`（违规逐步归零；`--check` 只在全绿时 exit 0——子组未全清时用 `--report` 确认仅剩目标文件）→ `pytest tests/test_style_guardrails.py tests/test_rss_sidebar.py -v` → 截图 rss 聚合页明/暗（**重点人工确认**：torrent 状态色、未读高亮、侧栏选中态零退化）。

- [ ] **Step 6: 提交（每子组一个）**

```bash
git add core/theme/tokens.py modules/rss_aggregator/text_utils.py tests/test_style_guardrails.py
git commit -m "refactor(style): rss_aggregator 主色板并入全局色板（8A）"
# 8B / 8C 各自一次，前缀同 refactor(style):
```

---

### Task 9: 全局收尾——qss 兜底收敛 + 豁免收窄 + 最终验收（spec:58、111）

**Files:** `core/theme/qss_dark.py`、`core/theme/qss_light.py`、`scripts/audit_styles.py`（whitelist 最小化）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: whitelist 收窄至 `{core/theme/tokens.py, ui/widgets.py, scripts/audit_styles.py, tests/}`；audit `--check` 零新增；qss 兜底文件内分散色值 → `theme_palette()` 引用

- [ ] **Step 1: qss_dark/qss_light 色值收敛**

两个文件内分散 hex → `f"{palette[...]}"` 引用（`from core.theme.tokens import theme_palette`，函数内 `p = theme_palette()` 后 QSS 字符串用 f-string 插值）。文件末尾/函数内自检：文件内无裸 `#hex`（`rgba(...)` 合成除外，若 palette 值本身为 rgba 字符串则正常）。此步骤视觉零变化（值不变，仅改来源）。

- [ ] **Step 2: whitelist 收窄至最小集**

`scripts/audit_styles.py` whitelist 删除 `core/theme/qss_dark.py`、`core/theme/qss_light.py`、`modules/perf_monitor/styles.py`（T4 已删）、perf whitelist 注释中的阶段 3 迁移后说明；仅保留 `core/theme/tokens.py`、`ui/widgets.py`、`scripts/audit_styles.py`、`tests/`。

- [ ] **Step 3: 重建基线 + 终验**

Run: `python scripts/audit_styles.py --init && python scripts/audit_styles.py --check`（qss 收敛后无新 hex；基线 total 应降至仅剩豁免文件外真实余量——理论为 0 或接近；若 qss 收敛遗漏 → 新基线捕获并修复）→ `pytest -v`（全量）→ 全套明/暗截图（`yzplan_screenshot_yzplan` + 各模块 widget）。

**最终验收清单（spec §6）**：
- [ ] `python scripts/audit_styles.py --check` → exit 0，0 新增违规
- [ ] `pytest -v` → 全绿（含护栏、rss 侧栏、perf）
- [ ] 明/暗主题全套截图人工确认零退化
- [ ] whitelist == 最小集（4 项）

- [ ] **Step 4: 提交**

```bash
git add core/theme/qss_dark.py core/theme/qss_light.py scripts/audit_styles.py scripts/styles_audit_baseline.json
git commit -m "refactor(style): qss 兜底收敛至 theme_palette 引用 + 豁免收窄至最小集；baseline N→0"
```

---

## 任务依赖与顺序

```
T1 (tokens/audit 规则) ──┬─→ T3 (ui/) ─┐
                         ├─→ T4 (perf) ─┤
T2 (测试加固) ───────────┼─→ T5 (todo/sys) ─┼─→ T9 (收尾/终验)
                         ├─→ T6 (webview/translator) ─┤
                         ├─→ T7 (其余 + P-10) ─┘
                         └─→ T8 (rss，gate 后) ───────┘
```

- T4 依赖 T2 的 `perf_palette` 结构断言（T2 先改引用名，T4 改名后同步）；若 T2 先行时 `_theme_colors` 未改名，T2 的断言暂保留旧名、T4 中一并改。
- T8 是唯一有外部协调门槛的任务（协作者改动冻结）。
- 每个任务独立可审查（TDD 红→绿→commit）；T9 是唯一"跨全库"宽任务（qss 两文件），其余宽幅均在模块内。

## Self-Review

- **Spec 覆盖**：§4 顺序 ①ui/→②perf→③todo/sys/webview/translator→④rss ✓（T3/T4/T5/T6/T8）；"每个模块替换后截图对比明/暗" ✓（T3-T8 各含截图步）；§5 护栏 A（工厂）不变、B 静态扫描扩 `size_literal` + 行内豁免（T1/T7）、C 运行时护栏新增 rss 断言（T8 Step 4）、D 规范不变（AGENTS.md）；§6 验证：audit 零违规/全量 pytest/明暗截图（T9 最终验收清单）；spec:58 qss 兜底收敛 ✓（T9）。
- **占位符扫描**：无 TBD/TODO；每任务的"执行指示"给出判定准则（P-9 映射决策）而非空话；代码块为完整可实现片段。
- **类型一致性**：`perf_palette` 名在 T2（结构断言引用）/T4（改名主）/test_perf_monitor_ui 三处一致；`status_error/warning/info` 在 T6 定义、T7 消费一致；`log_info/warning/error/critical/source` 在 T3 定义使用一致；`rss_*` 专区在 T8 定义消费一致；`sizing()` 新 key（`input_h_padding` 等 5 + `toolbar_height`/`title_bar_height`/`log_table_min_height` 3）在 T1/T3 各自定义与使用一致。

**Known risks（记录不阻塞）**：T5 日历色"直映射 vs 保原值"依赖执行期截图人工判断（色差 ≤3% L\* 视同无退化）；T8 的 `rss_*` key 集合依赖执行时读取 `text_utils.py` 现存键（计划无法预穷举，已给穷举指令）；T9 假定 qss 收敛后无遗留 hex，若违反则在重建基线后修复（护栏尽责）。